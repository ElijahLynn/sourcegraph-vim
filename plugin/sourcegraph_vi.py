import os
import sys
import vim
sys.path.append(os.path.dirname(vim.eval("s:path")))
import sourcegraph_lib

sourcegraph_instance = sourcegraph_lib.Sourcegraph(sourcegraph_lib.Settings())
sourcegraph_instance.post_load()
filename = vim.eval("s:filename")
curr_word = vim.eval("s:currword")
curr_offset = vim.eval("s:curroffset")
numlines = int(vim.eval("s:numlines"))
lines = []
for i in range(1, numlines+1):
        currline = vim.eval("getline('%s')" % str(i))
        lines.append(currline)
        preceding_selection = "\n".join(lines)
args = sourcegraph_lib.LookupArgs(filename=filename, cursor_offset=curr_offset, preceding_selection="\n".join(lines), selected_token=curr_word)
sourcegraph_instance.on_selection_modified_handler(args)
