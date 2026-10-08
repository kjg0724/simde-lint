# Instructions in each function body: everything from the symbol header up to
# and including the first `ret`. Alignment padding after `ret` belongs to no
# function and is not counted; counting it inflated an earlier reading by two.
/^[0-9a-f]+ <.*>:/ { name=$2; gsub(/[<>:]/,"",name); order[++k]=name; cur=name; n[cur]=0; done[cur]=0; next }
/^ *[0-9a-f]+:/ {
  if (cur == "" || done[cur]) next
  if ($0 ~ /\tret/) { done[cur]=1; next }
  n[cur]++
}
END { for (i=1;i<=k;i++) printf "%-22s %d\n", order[i], n[order[i]] }
