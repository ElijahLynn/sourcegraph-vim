let s:path = fnamemodify(resolve(expand('<sfile>:p')), ':h')."/sourcegraph_vi.py"

if !has('python')
	finish
endif

function! LookupSymbol()
	let s:filename = expand('%p')
	let s:currword = expand('<cword>') 
	let s:curroffset = line2byte(line("."))+col(".")
	let s:numlines = expand(line('$'))
	execute "pyfile " . s:path
endfunc

command! GRAPH call LookupSymbol()
nnoremap <F2> :GRAPH<CR>
