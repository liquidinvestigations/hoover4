use super::*;
use serde_json::json;

struct Rows(Vec<(Vec<String>, Value)>);

impl RowSink for Rows {
    fn row(&mut self, sheet_path: &[String], value: Value) -> Result<(), String> {
        self.0.push((sheet_path.to_vec(), value));
        Ok(())
    }
}

fn sheets_of(text: &str) -> Vec<Sheet> {
    let mode = detect_mode(text.as_bytes(), true).expect("json");
    let mut discovery = Discovery::default();
    match mode {
        Mode::Json => walk_json(text.as_bytes(), &mut discovery).unwrap(),
        Mode::JsonLines => walk_json_lines(text.as_bytes(), &mut discovery).unwrap(),
    }
    discovery.sheets(mode)
}

fn labels(sheet: &Sheet) -> Vec<String> {
    sheet.schema.columns.iter().map(|c| c.label.clone()).collect()
}

#[test]
fn dotted_keys_stay_distinct_from_nested_paths() {
    let sheets = sheets_of(r#"[{"a.b": 1, "a": {"b": 2}}]"#);
    assert_eq!(labels(&sheets[0]), vec!["a\\.b", "a.b"]);
    assert_eq!(sheets[0].schema.columns[0].path, vec!["a.b".to_string()]);
    assert_eq!(sheets[0].schema.columns[1].path, vec!["a".to_string(), "b".to_string()]);
    let cells = sheets[0].schema.cells(&json!({"a.b": 1, "a": {"b": 2}}));
    assert_eq!(cells, vec![(1, CellKind::Number, "1".into()), (2, CellKind::Number, "2".into())]);
}

#[test]
fn labels_are_reversible() {
    for path in [vec!["a.b".to_string(), "".into(), "c\\d".into()], vec!["$".into()], vec!["*".into(), "x".into()]] {
        assert_eq!(path_of(&label_of(&path)), path);
    }
    assert_eq!(label_of(&[]), "$");
}

#[test]
fn numbers_keep_their_source_text() {
    let sheets = sheets_of(r#"[{"id": 123456789012345678901234567890, "x": 1.50, "e": 1E400}]"#);
    let row: Value = serde_json::from_str(r#"{"id": 123456789012345678901234567890, "x": 1.50, "e": 1E400}"#).unwrap();
    let cells = sheets[0].schema.cells(&row);
    assert_eq!(cells[0].2, "123456789012345678901234567890");
    assert_eq!(cells[1].2, "1.50");
    // The parser writes an exponent in lower case with its sign. The digits stay exact.
    assert_eq!(cells[2].2, "1e+400");
}

#[test]
fn null_is_a_cell_and_missing_is_none() {
    let text = "{\"a\": null, \"b\": 1}\n{\"b\": 2}\n";
    let sheets = sheets_of(text);
    assert_eq!(sheets[0].name, "");
    assert_eq!(labels(&sheets[0]), vec!["a", "b"]);
    assert_eq!(sheets[0].schema.cells(&json!({"a": null, "b": 1}))[0], (1, CellKind::Null, "null".into()));
    assert_eq!(sheets[0].schema.cells(&json!({"b": 2})), vec![(2, CellKind::Number, "2".into())]);
}

#[test]
fn late_columns_get_later_ids_and_mixed_rows_use_the_root_column() {
    let text = "{\"a\": 1}\n[1, 2]\n{\"a\": 2, \"z\": {\"y\": true}}\n";
    let sheets = sheets_of(text);
    assert_eq!(labels(&sheets[0]), vec!["$", "a", "z.y"]);
    assert_eq!(sheets[0].schema.cells(&json!([1, 2])), vec![(1, CellKind::Json, "[1,2]".into())]);
}

#[test]
fn scalar_and_object_at_one_path_get_two_columns() {
    let sheets = sheets_of(r#"[{"a": 1}, {"a": {"b": 2}}, {"a": {}}]"#);
    assert_eq!(labels(&sheets[0]), vec!["a", "a.b"]);
    assert_eq!(sheets[0].schema.cells(&json!({"a": {}})), vec![(1, CellKind::Json, "{}".into())]);
}

#[test]
fn duplicate_keys_keep_the_last_value() {
    let row: Value = serde_json::from_str(r#"{"a": 1, "a": 2}"#).unwrap();
    let sheets = sheets_of(r#"[{"a": 1, "a": 2}]"#);
    assert_eq!(sheets[0].schema.cells(&row), vec![(1, CellKind::Number, "2".into())]);
}

#[test]
fn arrays_inside_rows_are_json_text() {
    let sheets = sheets_of(r#"[{"tags": ["x", "y"], "kids": [{"n": 1}]}]"#);
    let cells = sheets[0].schema.cells(&json!({"tags": ["x", "y"], "kids": [{"n": 1}]}));
    assert_eq!(cells[0].2, "[\"x\",\"y\"]");
    assert_eq!(cells[1].2, "[{\"n\":1}]");
}

#[test]
fn sheets_are_found_up_to_depth_three() {
    let text = r#"{"type": "Topology", "objects": {"states": {"geometries": [{"id": 1}]}},
                 "a": {"b": {"c": {"d": [{"x": 1}]}}}, "list": [{"k": 1}], "nums": [1, 2]}"#;
    let sheets = sheets_of(text);
    let names: Vec<String> = sheets.iter().map(|s| s.name.clone()).collect();
    assert_eq!(names, vec!["$.objects.states.geometries", "$.list"]);
}

#[test]
fn an_object_without_arrays_of_objects_has_no_sheet() {
    assert!(sheets_of(r#"{"alice": {"age": 3}, "bob": {"age": 4}}"#).is_empty());
    assert!(sheets_of(r#"[1, 2, 3]"#).is_empty());
}

#[test]
fn wide_nested_objects_collapse_deterministically() {
    let mut row = Map::new();
    let mut big = Map::new();
    for i in 0..600 {
        big.insert(format!("k{i}"), json!(i));
    }
    let mut small = Map::new();
    for i in 0..600 {
        small.insert(format!("s{i}"), json!(i));
    }
    row.insert("first".into(), Value::Object(big));
    row.insert("second".into(), Value::Object(small));
    row.insert("id".into(), json!(1));
    let text = serde_json::to_string(&vec![Value::Object(row.clone())]).unwrap();
    let a = sheets_of(&text);
    let b = sheets_of(&text);
    assert_eq!(labels(&a[0]), labels(&b[0]));
    assert!(a[0].schema.columns.len() <= MAX_COLUMNS);
    // Both objects have 600 columns. The earlier one collapses on the tie.
    assert_eq!(a[0].schema.columns[0].label, "first");
    assert!(a[0].schema.columns[0].json);
    assert_eq!(a[0].schema.columns.len(), 1 + 600 + 1);
    let cells = a[0].schema.cells(&Value::Object(row));
    assert!(cells[0].2.starts_with("{\"k0\":0"));
}

#[test]
fn flat_records_over_the_limit_use_the_rest_column() {
    let mut row = Map::new();
    for i in 0..1500 {
        row.insert(format!("c{i}"), json!(i));
    }
    let text = serde_json::to_string(&vec![Value::Object(row.clone())]).unwrap();
    let sheets = sheets_of(&text);
    let columns = &sheets[0].schema.columns;
    assert_eq!(columns.len(), MAX_COLUMNS);
    assert_eq!(columns[998].label, "c998");
    assert_eq!(columns[999].label, "*");
    let cells = sheets[0].schema.cells(&Value::Object(row));
    assert_eq!(cells.len(), MAX_COLUMNS);
    let rest: Value = serde_json::from_str(&cells[999].2).unwrap();
    assert_eq!(rest.as_object().unwrap().len(), 501);
}

#[test]
fn schema_memory_is_bounded() {
    let mut schema = Schema::default();
    for i in 0..(MAX_SCHEMA_NODES + 10) {
        schema.observe(&json!({format!("k{i}"): 1}));
    }
    assert!(schema.live <= MAX_SCHEMA_NODES);
    let frozen = schema.freeze();
    assert_eq!(frozen.columns.len(), MAX_COLUMNS);
    assert!(frozen.columns.last().unwrap().rest);
}

#[test]
fn mode_detection() {
    assert_eq!(detect_mode(b"{\"a\":1}\n{\"a\":2}\n", true), Ok(Mode::JsonLines));
    assert_eq!(detect_mode(b"{\n\t\"a\": [1]\n}\n", true), Ok(Mode::Json));
    assert_eq!(detect_mode(b"{\"a\":1}\n", true), Ok(Mode::Json));
    assert_eq!(detect_mode(b"\xEF\xBB\xBF[{\"a\":1}]", true), Ok(Mode::Json));
    assert!(detect_mode(b"a,b\n1,2\n", true).is_err());
    assert!(detect_mode(b"\xFF\xFE[\x00", true).is_err());
    // A CSV line whose first field is JSON is not a JSON Lines file.
    assert_eq!(detect_mode(b"{\"a\":1},x\n{\"a\":2},y\n", true), Ok(Mode::Json));
}

#[test]
fn deep_nesting_fails_the_read() {
    let text = "[".repeat(1000) + &"]".repeat(1000);
    let mut rows = Rows(Vec::new());
    assert!(walk_json(text.as_bytes(), &mut rows).is_err());
}

#[test]
fn a_bad_json_lines_row_names_its_line() {
    let mut rows = Rows(Vec::new());
    let error = walk_json_lines("{\"a\":1}\n{oops\n".as_bytes(), &mut rows).unwrap_err();
    assert!(error.starts_with("line 2"), "{error}");
}

#[test]
fn cell_text_is_capped_on_a_character_boundary() {
    let text = "é".repeat(MAX_CELL_OUTPUT_BYTES);
    let capped = cap_text(text);
    assert!(capped.len() <= MAX_CELL_OUTPUT_BYTES);
    assert!(capped.len() > 64 * 1024);
}
