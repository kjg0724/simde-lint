# Instructions in each function body: everything between the symbol header and
# the first `ret`, with the `ret` itself excluded -- every function here ends
# in exactly one, so counting it would add the same constant to every row and
# obscure what the idiom costs. A single `dup` reads as 1. Alignment padding
# after `ret` belongs to no function and is not counted either; counting it
# inflated an earlier reading of the GCC results by two.
/^[0-9a-f]+ <.*>:/ { name=$2; gsub(/[<>:]/,"",name); order[++k]=name; cur=name; n[cur]=0; done[cur]=0; next }
/^ *[0-9a-f]+:/ {
  if (cur == "" || done[cur]) next
  if ($0 ~ /\tret/) { done[cur]=1; next }
  n[cur]++
}
END { for (i=1;i<=k;i++) printf "%-22s %d\n", order[i], n[order[i]] }
