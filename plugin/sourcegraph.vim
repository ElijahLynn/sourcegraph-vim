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
let s:last_word_small = ''
let s:last_offset = 0
let s:last_linenumber = -1

au BufNewFile,BufRead *.go set filetype=go

function! LookupSymbol()
	echo ""
	if (&ft=='go')
    	let s:filename = expand('%p')
		let s:currword = expand('<cWORD>')
		let s:currword_small = expand('<cword>')
		let s:curroffset = line2byte(line("."))+col(".")-1
		let s:numlines = expand(line('$'))
		let s:linenumber = expand(line("."))
		if(s:filename==s:last_filename && s:currword_small==s:last_word_small && s:linenumber==s:last_linenumber)
		else
			let s:last_filename = s:filename
			let s:last_word = s:currword
			let s:last_word_small = s:currword_small
			let s:last_offset = s:curroffset
			let s:last_linenumber = s:linenumber
			execute "pyfile " . s:path
		endif
	endif
endfunc

command! GRAPH call LookupSymbol()

