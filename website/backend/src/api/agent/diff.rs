//! A unified line diff for `documents/diff_sources`.
//!
//! No existing backend read composes a diff between two text sources: the browser's
//! source selector shows one text at a time and never two side by side. This is
//! therefore new code rather than a composition, an ordinary line-based unified diff
//! over the longest common subsequence of lines, bounded so one pathological pair of
//! documents cannot hold a request open.

/// Lines above this on either side skip the exact diff and report a summary instead.
/// The LCS table below is `O(lines_a * lines_b)` cells, so an unbounded pair of large
/// documents is a quadratic memory and time cost this route must not accept.
const MAX_DIFF_LINES: usize = 4_000;

/// A unified diff of `text_a` against `text_b`, `---`/`+++` headers named by the two
/// source strings.
pub fn unified_diff(text_a: &str, text_b: &str, label_a: &str, label_b: &str) -> String {
    let lines_a: Vec<&str> = text_a.lines().collect();
    let lines_b: Vec<&str> = text_b.lines().collect();

    if lines_a.len() > MAX_DIFF_LINES || lines_b.len() > MAX_DIFF_LINES {
        return format!(
            "--- {label_a}\n+++ {label_b}\n@@ diff skipped @@\n{} has {} lines and {} has {} lines; \
             one of them is over the {MAX_DIFF_LINES}-line bound this route diffs exactly.\n",
            label_a,
            lines_a.len(),
            label_b,
            lines_b.len(),
        );
    }

    let ops = diff_ops(&lines_a, &lines_b);
    render_unified(&lines_a, &lines_b, &ops, label_a, label_b)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DiffOp {
    Equal,
    Delete,
    Insert,
}

/// One row per line of `a` (0 to `len(a)`), one column per line of `b`: the classic
/// longest-common-subsequence table, walked backward into a list of equal/delete/insert
/// operations in forward order.
fn diff_ops(a: &[&str], b: &[&str]) -> Vec<(DiffOp, usize, usize)> {
    let (n, m) = (a.len(), b.len());
    let mut lcs = vec![vec![0u32; m + 1]; n + 1];
    for i in (0..n).rev() {
        for j in (0..m).rev() {
            lcs[i][j] = if a[i] == b[j] {
                lcs[i + 1][j + 1] + 1
            } else {
                lcs[i + 1][j].max(lcs[i][j + 1])
            };
        }
    }

    let mut ops = Vec::new();
    let (mut i, mut j) = (0, 0);
    while i < n && j < m {
        if a[i] == b[j] {
            ops.push((DiffOp::Equal, i, j));
            i += 1;
            j += 1;
        } else if lcs[i + 1][j] >= lcs[i][j + 1] {
            ops.push((DiffOp::Delete, i, j));
            i += 1;
        } else {
            ops.push((DiffOp::Insert, i, j));
            j += 1;
        }
    }
    while i < n {
        ops.push((DiffOp::Delete, i, j));
        i += 1;
    }
    while j < m {
        ops.push((DiffOp::Insert, i, j));
        j += 1;
    }
    ops
}

/// Group consecutive operations into hunks with three lines of context, and render each
/// as `@@ -a_start,a_len +b_start,b_len @@` followed by ` `/`-`/`+` lines, the format
/// `patch` and every diff-reading tool accepts.
fn render_unified(
    a: &[&str],
    b: &[&str],
    ops: &[(DiffOp, usize, usize)],
    label_a: &str,
    label_b: &str,
) -> String {
    const CONTEXT: usize = 3;

    if ops.iter().all(|(op, _, _)| *op == DiffOp::Equal) {
        return format!("--- {label_a}\n+++ {label_b}\n");
    }

    let mut out = format!("--- {label_a}\n+++ {label_b}\n");
    let mut index = 0;
    while index < ops.len() {
        if ops[index].0 == DiffOp::Equal {
            index += 1;
            continue;
        }
        // Walk backward into the context before this change, and forward through
        // every change and its surrounding equal runs until a run longer than twice
        // the context separates it from the next change: that gap is where the hunk
        // may legally end.
        let hunk_start = index.saturating_sub(CONTEXT);
        let mut hunk_end = index;
        while hunk_end < ops.len() {
            if ops[hunk_end].0 != DiffOp::Equal {
                hunk_end += 1;
                continue;
            }
            let mut run_end = hunk_end;
            while run_end < ops.len() && ops[run_end].0 == DiffOp::Equal {
                run_end += 1;
            }
            if run_end - hunk_end > CONTEXT * 2 || run_end == ops.len() {
                hunk_end += CONTEXT.min(run_end - hunk_end);
                break;
            }
            hunk_end = run_end;
        }

        let (a_start, b_start) = (ops[hunk_start].1, ops[hunk_start].2);
        let (mut a_len, mut b_len) = (0usize, 0usize);
        let mut body = String::new();
        for (op, ai, bi) in &ops[hunk_start..hunk_end] {
            match op {
                DiffOp::Equal => {
                    body.push_str(" ");
                    body.push_str(a[*ai]);
                    body.push('\n');
                    a_len += 1;
                    b_len += 1;
                }
                DiffOp::Delete => {
                    body.push('-');
                    body.push_str(a[*ai]);
                    body.push('\n');
                    a_len += 1;
                }
                DiffOp::Insert => {
                    body.push('+');
                    body.push_str(b[*bi]);
                    body.push('\n');
                    b_len += 1;
                }
            }
        }
        out.push_str(&format!(
            "@@ -{},{} +{},{} @@\n",
            a_start + 1,
            a_len,
            b_start + 1,
            b_len
        ));
        out.push_str(&body);
        index = hunk_end;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identical_texts_have_no_hunks() {
        let diff = unified_diff("a\nb\nc\n", "a\nb\nc\n", "left", "right");
        assert_eq!(diff, "--- left\n+++ right\n");
    }

    #[test]
    fn a_single_changed_line_produces_one_hunk() {
        let diff = unified_diff("a\nb\nc\n", "a\nx\nc\n", "left", "right");
        assert!(diff.contains("@@ -1,3 +1,3 @@"), "{diff}");
        assert!(diff.contains("-b"), "{diff}");
        assert!(diff.contains("+x"), "{diff}");
        assert!(diff.contains(" a"), "{diff}");
        assert!(diff.contains(" c"), "{diff}");
    }

    #[test]
    fn an_appended_line_is_a_pure_insert() {
        let diff = unified_diff("a\nb\n", "a\nb\nc\n", "left", "right");
        assert!(diff.contains("+c"), "{diff}");
        assert!(!diff.contains("-a"), "{diff}");
        assert!(!diff.contains("-b"), "{diff}");
    }

    #[test]
    fn a_document_over_the_line_bound_is_summarised_not_diffed() {
        let huge = "line\n".repeat(MAX_DIFF_LINES + 1);
        let diff = unified_diff(&huge, "line\n", "left", "right");
        assert!(diff.contains("diff skipped"), "{diff}");
    }
}
