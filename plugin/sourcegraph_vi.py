import os
import sys
import vim
from threading import Thread
sys.path.append(os.path.dirname(vim.eval("s:path")))
import sourcegraph_lib

def get_vim_variable(variable_name):
	var_exists = vim.eval("exists('%s')" % variable_name)
	if var_exists is not '0':
		return vim.eval(variable_name)
	return None

def get_channel():
	variable_name = "g:SOURCEGRAPH_CHANNEL"
	var_exists = vim.eval("exists('%s')" % variable_name)
	if var_exists is not '0':
		return vim.eval(variable_name)
	else:
		channel_id = sourcegraph_lib.generate_channel_id()
		vim.command("let %s = '%s'" % (variable_name, channel_id))
		return channel_id

sourcegraph_lib.SG_LOG_FILE = '/tmp/sourcegraph-vim.log'
settings = sourcegraph_lib.Settings()
channel_id = get_channel()
settings.SG_CHANNEL = channel_id
settings.EditorType = "vim"

gopath = get_vim_variable('g:SOURCEGRAPH_GOPATH')
if gopath:
	settings.ENV['GOPATH'] = str(gopath.rstrip(os.sep)).strip()
auto = get_vim_variable('g:SOURCEGRAPH_AUTO')
if auto:
	settings.AUTO = bool(auto)
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

def add_symbol_task(filename, curr_word, curr_offset, numlines):
	lines = []
	for i in range(1, numlines + 1):
		currline = vim.eval("getline('%s')" % str(i))
		lines.append(currline)
	preceding_selection = "\n".join(lines)
	args = sourcegraph_lib.LookupArgs(filename=filename, cursor_offset=curr_offset, preceding_selection="\n".join(lines), selected_token=curr_word)
	sourcegraph_lib.request_manager.add(args)

def startup():
	sourcegraph_lib.request_manager.setup(settings)
	sourcegraph_lib.request_manager.update()

if vim.eval("s:startup") == "true":
	t = Thread(target=startup)
	t.setDaemon(True)
	t.start()
else:
	add_symbol_task(vim.eval("s:filename"), vim.eval("s:currword"), vim.eval("s:curroffset"), int(vim.eval("s:numlines")) )
