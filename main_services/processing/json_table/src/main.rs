//! `json-table <file>`: write the table sheets of a JSON or JSON Lines file to stdout.
//!
//! Exit status 0 with a `none` line means valid input without a table. Exit status 1
//! means a read error, with the message on stderr. See `Readme.md` for the protocol.

use std::collections::HashMap;
use std::fs::File;
use std::io::{self, BufReader, BufWriter, Read, Seek, SeekFrom, Write};
use std::process::ExitCode;

use json_table::{
    detect_mode, walk_json, walk_json_lines, Discovery, Mode, RowSink, Sheet, MAX_COLUMNS, SAMPLE_BYTES,
};
use serde_json::{json, Value};

fn open_body(path: &str) -> io::Result<File> {
    let mut file = File::open(path)?;
    let mut bom = [0u8; 3];
    let n = file.read(&mut bom)?;
    if !(n == 3 && bom == [0xEF, 0xBB, 0xBF]) {
        file.seek(SeekFrom::Start(0))?;
    }
    Ok(file)
}

fn walk<S: RowSink>(path: &str, mode: Mode, sink: &mut S) -> Result<(), String> {
    match mode {
        Mode::Json => walk_json(open_body(path).map_err(|e| e.to_string())?, sink),
        Mode::JsonLines => walk_json_lines(
            BufReader::with_capacity(1 << 20, File::open(path).map_err(|e| e.to_string())?),
            sink,
        ),
    }
}

struct Emitter<'a, W: Write> {
    sheets: &'a [Sheet],
    by_path: HashMap<Vec<String>, usize>,
    rows: Vec<u64>,
    out: W,
}

impl<W: Write> RowSink for Emitter<'_, W> {
    fn row(&mut self, sheet_path: &[String], value: Value) -> Result<(), String> {
        let Some(&index) = self.by_path.get(sheet_path) else {
            return Ok(());
        };
        let sheet = &self.sheets[index];
        self.rows[index] += 1;
        let cells: Vec<Value> = sheet
            .schema
            .cells(&value)
            .into_iter()
            .map(|(id, kind, text)| json!([id, kind.code(), text]))
            .collect();
        let line = json!({"t": "row", "s": sheet.id, "r": self.rows[index], "c": cells});
        serde_json::to_writer(&mut self.out, &line).map_err(|e| e.to_string())?;
        self.out.write_all(b"\n").map_err(|e| e.to_string())
    }
}

fn none(out: &mut impl Write, reason: &str) -> ExitCode {
    let _ = writeln!(out, "{}", json!({"t": "none", "reason": reason}));
    ExitCode::SUCCESS
}

fn run(path: &str) -> Result<ExitCode, String> {
    let stdout = io::stdout();
    let mut out = BufWriter::with_capacity(1 << 20, stdout.lock());

    let mut file = File::open(path).map_err(|e| e.to_string())?;
    let size = file.metadata().map_err(|e| e.to_string())?.len();
    let mut sample = Vec::with_capacity(SAMPLE_BYTES);
    (&mut file).take(SAMPLE_BYTES as u64).read_to_end(&mut sample).map_err(|e| e.to_string())?;
    let mode = match detect_mode(&sample, size as usize <= SAMPLE_BYTES) {
        Ok(mode) => mode,
        Err(reason) => return Ok(none(&mut out, &reason.0)),
    };

    let mut discovery = Discovery::default();
    if let Err(error) = walk(path, mode, &mut discovery) {
        if discovery.candidates.iter().any(|c| c.objects > 0) {
            return Err(error);
        }
        return Ok(none(&mut out, &format!("not valid JSON: {error}")));
    }
    let sheets_truncated = discovery.sheets_truncated;
    let sheets = discovery.sheets(mode);
    if sheets.is_empty() {
        return Ok(none(&mut out, "no array of objects"));
    }

    let header: Vec<Value> = sheets
        .iter()
        .map(|sheet| {
            json!({
                "id": sheet.id,
                "name": sheet.name,
                "rows": sheet.rows,
                "collapsed": sheet.schema.collapsed_subtrees,
                "columns": sheet.schema.columns.iter().map(|c| json!({
                    "id": c.id, "label": c.label, "path": c.path, "json": c.json, "rest": c.rest,
                })).collect::<Vec<_>>(),
            })
        })
        .collect();
    writeln!(
        out,
        "{}",
        json!({"t": "sheets", "mode": mode.name(), "max_columns": MAX_COLUMNS,
               "sheets_truncated": sheets_truncated, "sheets": header})
    )
    .map_err(|e| e.to_string())?;

    let mut emitter = Emitter {
        sheets: &sheets,
        by_path: sheets.iter().enumerate().map(|(i, s)| (s.path.clone(), i)).collect(),
        rows: vec![0; sheets.len()],
        out: &mut out,
    };
    walk(path, mode, &mut emitter)?;
    writeln!(out, "{}", json!({"t": "end"})).map_err(|e| e.to_string())?;
    out.flush().map_err(|e| e.to_string())?;
    Ok(ExitCode::SUCCESS)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 2 {
        eprintln!("usage: json-table <file>");
        return ExitCode::from(2);
    }
    match run(&args[1]) {
        Ok(code) => code,
        Err(message) => {
            eprintln!("json-table: {message}");
            ExitCode::FAILURE
        }
    }
}
