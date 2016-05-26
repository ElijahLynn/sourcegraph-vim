import os
import sys
import vim
sys.path.append(os.path.dirname(vim.eval("s:path")))
import sourcegraph_lib

def get_vim_variable(variable_name):
	var_exists = vim.eval("exists('%s')" % variable_name)
	if var_exists is not '0':
		return vim.eval(variable_name)
	return None

settings = sourcegraph_lib.Settings()
gopath = get_vim_variable('g:SOURCEGRAPH_GOPATH')
if gopath:
	settings.ENV['GOPATH'] = str(gopath.rstrip(os.sep)).strip()
gobin = get_vim_variable('g:SOURCEGRAPH_GOBIN')
if gobin:
	settings.GOBIN = gobin.rstrip(os.sep)
log_level = get_vim_variable('g:SOURCEGRAPH_LOG_LEVEL')
if log_level:
	sourcegraph_lib.LOG_LEVEL = int(log_level)
enable_lookback = get_vim_variable('g:SOURCEGRAPH_ENABLE_LOOKBACK')
if enable_lookback:
	settings.ENABLE_LOOKBACK = bool(enable_lookback)
base_url = get_vim_variable('g:SOURCEGRAPH_BASE_URL')
if base_url:
	settings.SG_BASE_URL = base_url
log_file = get_vim_variable('g:SOURCEGRAPH_LOG_FILE')
if log_file:
	sourcegraph_lib.SG_LOG_FILE = log_file

sourcegraph_instance = sourcegraph_lib.Sourcegraph(settings)
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
