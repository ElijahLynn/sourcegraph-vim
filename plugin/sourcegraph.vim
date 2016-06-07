let s:path = fnamemodify(resolve(expand('<sfile>:p')), ':h')."/sourcegraph_vi.py"

if !has('python')
	finish
endif

let s:startup = "true"
let s:didOpenBrowser = "false"
execute "pyfile " . s:path
let s:startup = "false"

if (has('python') && (!exists("g:SOURCEGRAPH_AUTO") || g:SOURCEGRAPH_AUTO == "true"))
    augroup SourcegraphVim
        autocmd VimEnter     * :call LookupSymbol()
        autocmd VimLeavePre  * :call LookupSymbol()
        autocmd CursorMoved  * :call LookupSymbol()
        autocmd CursorMovedI * :call LookupSymbol()
        autocmd BufEnter     * :call LookupSymbol()
        autocmd BufLeave     * :call LookupSymbol()
    augroup END
endif

let s:last_filename = ''
let s:last_word = ''
let s:last_offset = 0

au BufNewFile,BufRead *.go set filetype=go

function! LookupSymbol()
	echo ""
	if (&ft=='go')
    	let s:filename = expand('%p')
		let s:currword = expand('<cWORD>')
		let s:curroffset = line2byte(line("."))+col(".")
		let s:numlines = expand(line('$'))
		if(s:filename==s:last_filename && s:currword==s:last_word)
		else
			let s:last_filename = s:filename
			let s:last_word = s:currword
			let s:last_offset = s:curroffset
			execute "pyfile " . s:path
		endif
	endif
endfunc

command! GRAPH call LookupSymbol()

nnoremap <F2> :GRAPH<CR>

