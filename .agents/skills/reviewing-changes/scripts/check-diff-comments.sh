#!/bin/sh
# One-line comment-hygiene report for a diff. Runs in well under a second.
#
#   check-diff-comments.sh              # working tree vs HEAD (staged + unstaged)
#   check-diff-comments.sh --staged     # staged only
#   check-diff-comments.sh <rev-range>  # any git range
#
# Prints one summary line, then one line per flagged added line. Exit status is 0
# always: this informs a patch, it does not gate one.
set -e
cd "$(git rev-parse --show-toplevel)"

case "$1" in
  --staged) DIFF="git diff --cached -U0 --no-color" ;;
  "")       DIFF="git diff HEAD -U0 --no-color" ;;
  *)        DIFF="git diff -U0 --no-color $1" ;;
esac

$DIFF -- '*.py' '*.rs' '*.sql' '*.sh' \
    ':(exclude)plans' ':(exclude)testdata' \
    ':(exclude)main_services/regex_entity_scanner/vendored' \
    ':(exclude)website/frontend/assets/embed-pdf' \
    ':(exclude)website/backend/pdf-viewer' |
awk '
/^\+\+\+ b\// { file = substr($0, 7); next }
/^\+/ && !/^\+\+\+/ {
  line = substr($0, 2)
  s = line; gsub(/^[ \t]+|[ \t]+$/, "", s)
  if (s == "") next
  is_c = (s ~ /^(#|\/\/|--|\/\*|\*)/) && s !~ /^#!/ && s !~ /^#\[/
  if (is_c) com++; else code++
  if (!is_c) next

  payload = s; sub(/^(#+|\/\/+|--+|\/\*+|\*)[ \t]*/, "", payload)

  # banner / divider
  if (payload ~ /^[-=*_ ~]*$/ || payload ~ /[-=*_]{5,}[ \t]*$/) { ban++; next }

  # commented-out code. Prose vetoes the syntactic tells, because English sentences
  # end in punctuation too and a comment that reads as a sentence is a comment.
  prose = (payload ~ /(^| )(the|a|an|is|are|we|this|that|so|but|because|it|not|and|to|of|which|when|why)( |,|\.)/)
  if (!prose && (payload ~ /^(let |const |var |fn |def |class |import |from |use |pub |return |if |for |while |print\(|println!|console\.|await |async |SELECT |INSERT |CREATE |DROP |ALTER )/ \
      || payload ~ /[;{}][ \t]*$/ || payload ~ /^[a-zA-Z_.]+\(.*\)[ \t]*;?[ \t]*$/)) {
    print "  commented-out code   " file ": " substr(s,1,90); flag++; next
  }
  # forbidden: plan / phase labels
  if (payload ~ /([Pp]lan [0-9]|[Pp]lans\/|[Pp]hase [0-9]|[Pp]art [0-9]|the plan\b|design doc|the epic)/) {
    print "  plan/phase reference " file ": " substr(s,1,90); flag++; next
  }
  # forbidden: dates and commit hashes as a record of when
  if (payload ~ /(^|[^0-9])(19|20)[0-9][0-9]-[01][0-9]-[0-3][0-9]/ && payload ~ /(on |as of |since |added|changed|fixed|updated)/) {
    print "  date as history      " file ": " substr(s,1,90); flag++; next
  }
  # forbidden: aspirational / work-state
  if (payload ~ /(TODO|FIXME|XXX|HACK|[Rr]evisit|for now,|not yet implemented|will land|lands later|deferred|coming soon|[Ss]tep [0-9]+ of the|once .* lands)/) {
    print "  aspirational / TODO  " file ": " substr(s,1,90); flag++; next
  }
  # forbidden: narrating the change rather than the system
  if (payload ~ /([Pp]reviously|[Uu]sed to be|was renamed|this (session|commit|change|patch|PR)|we (now|just) (added|changed|removed|renamed)|until this .* existed|now that .* (landed|exists))/) {
    print "  narrates the change  " file ": " substr(s,1,90); flag++; next
  }
  # restates the identifier: a one-line doc comment whose words all appear in the
  # next code line as identifier fragments is filler
}
END {
  tot = com + code
  share = tot ? (100 * com / tot) : 0
  printf "comments: %d/%d added lines (%.0f%%)  banners: %d  flagged: %d\n", com, tot, share, ban+0, flag+0
  if (share > 40 && tot > 40) print "  NOTE: over 40% of this patch is comment; check it explains rather than restates."
}
'
