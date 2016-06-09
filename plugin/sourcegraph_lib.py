import json
import logging
import os
import random
import subprocess
import sys
import time

from Queue import Queue
from threading import Thread, Lock
try:
	from urllib.request import Request, urlopen
	from urllib.error import HTTPError, URLError
except:
	from urllib2 import Request, urlopen
	from urllib2 import HTTPError, URLError

ERROR_CALLBACK = None
SUCCESS_CALLBACK = None
STATUS_BAD = 0
STATUS_GOOD = 1

LOG_NONE = 0
LOG_SYMBOLS = 1
LOG_NETWORK = 2
LOG_ALL = 3

LOG_LEVEL = LOG_NONE
SG_LOG_FILE = '/tmp/sourcegraph-editor.log'

LOCK = Lock()

class Request_Manager():

	def update(self):
		item = self.q.get(True)
		self.sourcegraph_instance.on_selection_modified_handler(item)
		self.update()

	def add(self, item):
		self.q.queue.clear()
		self.q.put(item)

	def setup(self, settings):
		self.sourcegraph_instance = Sourcegraph(settings)
		self.sourcegraph_instance.post_load(godefinfo_update=True)

	def __init__(self):
		self.q = Queue()

request_manager = Request_Manager()

class Error(object):
	def __init__(self, title, description):
		self.title = title
		self.description = description

	def __str__(self):
		return "%s : %s" % (self.title, self.description)

ERR_GOPATH_UNDEFINED = Error('GOPATH Error', 'No valid GOPATH found in your shell startup scripts or Sublime settings. Please read the GOPATH section in the Sourcegraph Sublime README to learn how to manually set your GOPATH.')
ERR_GODEFINFO_INSTALL = Error('godefinfo binary not found', 'We could not find godefinfo in your PATH. Please read the godefinfo section in the Sourcegraph Sublime README to learn how to install godefinfo.')
ERR_GO_BINARY = Error('Go binary not found in your PATH', 'We could not find a Go binary in your PATH. Please read the GOBIN section in the Sourcegraph Sublime README to learn how to manually set your GOBIN.')
ERR_GO_VERSION = Error('Go version is < 1.6', 'Sourcegraph Sublime only works with Go 1.6 and greater. Please install Go 1.6.')
ERR_UNRECOGNIZED_SHELL = Error('Sourcegraph for Sublime can\'t execute commands against your shell', 'Contact Sourcegraph with your OS details, and we\'ll try to deliver Sourcegraph for your OS.')
ERR_GODEFINFO_INVALID = Error('godefinfo is not returning valid output', 'Please make sure you have selected a valid symbol, and have all imported packages installed on your computer.')

def is_windows():
	return os.name == 'nt'

def get_user_name():
	if is_windows():
		return os.environ.get('USERNAME')
	else:
		return os.environ.get('USER')

def get_home_path():
	if is_windows():
		return os.environ.get('HOMEPATH')
	else:
		return os.environ.get('HOME')

def find_gobin(shell):
	if is_windows():
		output, err, return_code = run_shell_command(['where', 'go'], None)
	else:
		output, err, return_code = run_native_shell_command(shell, ['which', 'go'])
	if return_code == 0 and output:
		return output.rstrip('.exe')
	else:
		return os.path.join('/usr', 'local', 'go', 'bin', 'go')

def shell_startup_info():
	if not is_windows():
		return None
	startup_info = subprocess.STARTUPINFO()
	startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	return startup_info

def get_gopaths(gopath_string):
	formatted_gopath_list = list()
	for gopath in gopath_string.split(os.pathsep):
		formatted_gopath_list.append(gopath.rstrip(os.sep).strip())

	return formatted_gopath_list

def find_gopath_from_shell(shell):
	if is_windows():
		if os.environ.get('GOPATH') and os.environ.get('GOPATH') != '':
			return get_gopaths(os.environ.get('GOPATH'))
		else:
			return None
	else:
		output, err, return_code = run_native_shell_command(shell, ['echo', '${GOPATH}'])
		if return_code == 0:
			return get_gopaths(output)
		else:
			log_output('[settings] Could not find GOPATH from shell: %s' % str(err))
			return None

def run_shell_command(command, env):
	try:
		log_output('Running shell command: %s' % ' '.join(command))
		process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, startupinfo=shell_startup_info())
		out, err = process.communicate()
		if out:
			out = out.decode().strip()
		if err:
			err = err.decode().strip()
		return out, err, process.returncode
	except Exception as e:
		return None, e, 1

def run_native_shell_command(shell_env, command):
	if isinstance(command, list):
		command = " ".join(command)
	native_command = [shell_env]
	if 'zsh' in shell_env:
		native_command += ['-i']
	native_command += ['-l', '-c', command]
	if not shell_env or shell_env == '':
		native_command = command.split()

	process = subprocess.Popen(native_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=shell_startup_info())
	out, err = process.communicate()
	log_output('Command %s output: %s' % (native_command, out))
	if out:
		out = out.decode().strip().split('\n')[-1]
	if err:
		err = err.decode().strip()
	return out, err, process.returncode

def check_filetype(filename):
	if filename is None or not filename.endswith('go'):
		return False
	return True

class Sourcegraph(object):
	def __init__(self, settings):
		super(Sourcegraph, self).__init__()
		self.EXPORTED_PARAMS_CACHE = None
		self.settings = settings

	def post_load(self, godefinfo_update=True):
		setup_logging()
		error_loading = self.add_gopath_to_path(godefinfo_update)
		if type(error_loading) is ExportedParams:
			self.send_curl_request(error_loading)
		log_output('[settings] env: %s' % str(self.settings.ENV))

	def on_selection_modified_handler(self, lookup_args):
		if not check_filetype(lookup_args.filename):
			return None
		validate_output = validate_settings(self.settings)
		if validate_output:
			log_major_failure(ERROR_CALLBACK, "%s: %s" % (validate_output.title, validate_output.description))
			return None
		return_object = self.get_sourcegraph_request(lookup_args.filename, lookup_args.cursor_offset, lookup_args.preceding_selection, lookup_args.selected_token)
		if return_object:
			return_object = self.send_curl_request(return_object)
			if SUCCESS_CALLBACK and return_object is not "CACHED":
				SUCCESS_CALLBACK()

	def get_sourcegraph_request(self, filename, cursor_offset, preceding_selection, selected_token):
		if self.settings.ENV.get('GOPATH') == '':
			return ExportedParams(Error=ERR_GOPATH_UNDEFINED.title, Fix=ERR_GOPATH_UNDEFINED.description, Status=STATUS_BAD, VersionMajor=self.settings.VersionMajor, VersionMinor=self.settings.VersionMinor, EditorType=self.settings.EditorType)

		stderr, godefinfo_output = self.run_godefinfo(filename, cursor_offset, preceding_selection)
		if stderr == b'FileNotFoundError':
			return ExportedParams(Error=ERR_GODEFINFO_INSTALL.title, Fix=ERR_GODEFINFO_INSTALL.description, Status=STATUS_BAD, VersionMajor=self.settings.VersionMajor, VersionMinor=self.settings.VersionMinor, EditorType=self.settings.EditorType)
		if stderr:
			log_symbol_failure(reason=stderr)
			return ExportedParams(Error=ERR_GODEFINFO_INVALID.title, Fix=ERR_GODEFINFO_INVALID.description, Status=STATUS_BAD, VersionMajor=self.settings.VersionMajor, VersionMinor=self.settings.VersionMinor, EditorType=self.settings.EditorType)

		godefinfo_parsed = godefinfo_output

		if godefinfo_parsed == '':
			log_symbol_failure(reason='[godefinfo] godefinfo returned nothing.')
			return ExportedParams(Error=ERR_GODEFINFO_INVALID.title, Fix=ERR_GODEFINFO_INVALID.description, Status=STATUS_BAD, VersionMajor=self.settings.VersionMajor, VersionMinor=self.settings.VersionMinor, EditorType=self.settings.EditorType)

		symbol_name = None

		def_components = godefinfo_parsed.split()
		repo_package = def_components[0]

		if '/vendor/' in repo_package:
			repo_package = repo_package.split('/vendor/')[1]
		if len(def_components) > 1:
			symbol_name = '/'.join(def_components[1:])

		if symbol_name or repo_package:
			log_output('\nParams: {Symbol: %s, Repo/package: %s}' % (str(symbol_name), str(repo_package)), is_symbol=True)
		else:
			log_symbol_failure(reason='Unable to find symbol or repo_package')

		return ExportedParams(Def=symbol_name, Repo=repo_package, Package=repo_package, Status=STATUS_GOOD, VersionMajor=self.settings.VersionMajor, VersionMinor=self.settings.VersionMinor, EditorType=self.settings.EditorType)

	def send_curl_request(self, exported_params):
		if self.EXPORTED_PARAMS_CACHE == exported_params:
			return "CACHED"
		self.EXPORTED_PARAMS_CACHE = exported_params
		post_url = '%s/.api/channel/%s' % (self.settings.SG_SEND_URL, self.settings.SG_CHANNEL)
		log_output('[network] Sending post request params: %s' % str(exported_params.to_json()), is_network=True)
		log_output('[network] Sending POST request to URL: %s' % post_url, is_network=True)
		req = Request(post_url, exported_params.to_json().encode('utf-8'), {'Content-Type': 'application/json'})
		t = Thread(target=self.send_curl_request_network, args=[req])
		t.start()

	def try_send(self, req):
		f = urlopen(req)
		status_code = f.getcode()
		log_output('[network] Server responded with code %s' % str(status_code), is_network=True)
		f.close()

	def send_curl_request_network(self, req):
		try:
			self.try_send(req)
		except HTTPError as err:
			global lock
			is_locked = LOCK.locked()
			LOCK.acquire(False)
			if is_locked == False:
				log_output('[network] Server responded with err code %s, reopening browser.' % str(err.code), is_network=True)
				self.open_channel()
				browser_window_has_opened = False
				request_attempts = 0
				while(not browser_window_has_opened and request_attempts < 5):
					try:
						self.try_send(req)
						browser_window_has_opened = True
						time.sleep(1)
					except Exception as err:
						request_attempts += 1
						log_output('[network] curl request failed twice, aborting. %s' % str(err), is_network=True)
				LOCK.release()
		except URLError as err:
			log_major_failure(ERROR_CALLBACK, 'Unable to reach the Sourcegraph API.\nPlease check your internet connection and try again.\n\nError: %s' % str(err))
		except Exception as err:
			log_major_failure(ERROR_CALLBACK, '[network] Unexpected exception: %s' % str(err))

	def open_channel_os(self):
		command = ['%s/-/channel/%s' % (self.settings.SG_BASE_URL, self.settings.SG_CHANNEL)]
		if sys.platform.startswith('linux'):
			command.insert(0, 'xdg-open')
		elif sys.platform == 'darwin':
			command.insert(0, 'open')
		elif is_windows():
			command.insert(0, 'explorer')
		else:
			command.insert(0, 'start')
		log_output('[open_channel] Opening channel in browser: %s' % command)
		run_shell_command(command, self.settings.ENV)
		time.sleep(2)

	def open_channel(self, hard_refresh=False):
		if hard_refresh:
			self.EXPORTED_PARAMS_CACHE = None
			self.settings.SG_CHANNEL = generate_channel_id()

		self.open_channel_os()

	def run_godefinfo(self, filename, cursor_offset, godefinfo_region):
		godefinfo_args = ["godefinfo", '-i', '-o', cursor_offset, '-f', filename]
		log_output('[godefinfo] Running shell command: %s' % ' '.join(godefinfo_args))
		godefinfo_output = b''
		stderr = None
		try:
			godefinfo_process = subprocess.Popen(godefinfo_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.settings.ENV, startupinfo=shell_startup_info())
			godefinfo_output, stderr = godefinfo_process.communicate(input=godefinfo_region)
			if godefinfo_output:
				godefinfo_output = godefinfo_output.decode()
			if stderr:
				log_output('[godefinfo] No definition found, returning. Message: %s' % stderr)
			else:
				log_output('[godefinfo] Output: %s' % godefinfo_output)
		except Exception:
			stderr = b'FileNotFoundError'
		return stderr, godefinfo_output

	def add_gopath_to_path(self, godefinfo_update=True):
		gopath_err = check_gopath(self.settings.ENV)
		if gopath_err:
			return gopath_err
		go_err = check_go(self.settings)
		if go_err:
			return go_err
		if self.settings.ENV.get('GOPATH') != '' and self.settings.ENV.get('GOPATH'):
			for gopath_loc in get_gopaths(self.settings.ENV['GOPATH']):
				self.settings.ENV['PATH'] += os.pathsep + os.path.join(gopath_loc, 'bin')
			return self.godefinfo_auto_install(self.settings.GOBIN, self.settings.ENV, godefinfo_update)
		else:
			log_output("[settings] Cannot find GOPATH, notifying error API.")
			return ExportedParams(Error=ERR_GOPATH_UNDEFINED.title, Fix=ERR_GOPATH_UNDEFINED.description, Status=STATUS_BAD, VersionMajor=self.settings.VersionMajor, VersionMinor=self.settings.VersionMinor, EditorType=self.settings.EditorType)

	def godefinfo_auto_install(self, gobin, env, godefinfo_update):
		if godefinfo_update:
			godefinfo_install_command = [gobin, 'get', '-u', 'github.com/sqs/godefinfo']
		else:
			godefinfo_install_command = [gobin, 'get', 'github.com/sqs/godefinfo']
		log_output('[godefinfo] Settings reloaded, installing godefinfo: %s' % ' '.join(godefinfo_install_command))
		out, err, return_code = run_shell_command(godefinfo_install_command, env)
		if return_code != 0:
			log_symbol_failure(reason='Godefinfo auto-install failure: %s' % str(err))
			return ExportedParams(Error=ERR_GO_BINARY.title, Fix=ERR_GO_BINARY.description, Status=STATUS_BAD, VersionMajor=self.settings.VersionMajor, VersionMinor=self.settings.VersionMinor, EditorType=self.settings.EditorType)
		return None


def generate_channel_id():
	return '%s-%06x%06x%06x%06x%06x%06x' % \
		(get_user_name(), random.randrange(16**6), random.randrange(16**6),
			random.randrange(16**6), random.randrange(16**6), random.randrange(16**6), random.randrange(16**6))


class LookupArgs(object):
	def __init__(self, filename, cursor_offset, selected_token, preceding_selection=None):
		self.filename = filename
		self.cursor_offset = cursor_offset
		self.preceding_selection = preceding_selection
		self.selected_token = selected_token

	def __eq__(self, other):
		if isinstance(other, LookupArgs):
			if self.filename != other.filename:
				return False
			if self.cursor_offset != other.cursor_offset:
				return False
			if self.selected_token != other.selected_token:
				return False
			if self.preceding_selection != other.preceding_selection:
				return False
			return True
		else:
			return NotImplemented

	def __ne__(self, other):
		result = self.__eq__(other)
		if result is NotImplemented:
			return result
		return not result

	def to_json(self):
		json_params = {}
		for param in self.__dict__:
			if self.__dict__[param] is not None:
				json_params[param] = self.__dict__[param]
		return json.dumps(json_params, ensure_ascii=False)

	def __str__(self):
		return self.to_json()


class Settings(object):
	def __init__(self, **kwds):
		super(Settings, self).__init__()
		self.SG_BASE_URL = 'https://sourcegraph.com'
		self.SG_SEND_URL = 'https://grpc.sourcegraph.com'
		self.ENV = os.environ.copy()
		self.AUTO = False
		self.ENABLE_LOOKBACK = True
		self.GOBIN = find_gobin(self.ENV.get('SHELL'))
		self.SG_CHANNEL = generate_channel_id()
		self.VersionMajor = 0
		self.VersionMinor = 1
		self.EditorType = "undefined"
		self.__dict__.update(kwds)

	def __str__(self):
		json_params = {}
		for param in self.__dict__:
			if self.__dict__[param]:
				json_params[param] = self.__dict__[param]
		return json.dumps(json_params, ensure_ascii=False)


class ExportedParams(object):
	def __init__(self, **kwds):
		super(ExportedParams, self).__init__()
		self.Repo = None
		self.Package = None
		self.Def = None
		self.Error = None
		self.Fix = None
		self.Type = None
		self.Status = STATUS_BAD
		self.VersionMajor = 0
		self.VersionMinor = 1
		self.EditorType = "undefined"
		self.__dict__.update(kwds)

	def __eq__(self, other):
		if isinstance(other, ExportedParams):
			if self.Repo != other.Repo:
				return False
			if self.Package != other.Package:
				return False
			if self.Def != other.Def:
				return False
			if self.Error != other.Error:
				return False
			if self.Fix != other.Fix:
				return False
			if self.Type != other.Type:
				return False
			if self.Status != other.Status:
				return False
			return True
		else:
			return NotImplemented

	def __ne__(self, other):
		result = self.__eq__(other)
		if result is NotImplemented:
			return result
		return not result

	def to_json(self):
		json_params = {'Action': {}, 'CheckForListeners': True}
		for param in self.__dict__:
			if self.__dict__[param] is not None:
				json_params['Action'][param] = self.__dict__[param]
		return json.dumps(json_params, ensure_ascii=False)

	def __str__(self):
		return self.to_json()

def setup_logging():
	root = logging.getLogger()
	if root.handlers:
		for handler in root.handlers:
			root.removeHandler(handler)
	logging.basicConfig(filename=SG_LOG_FILE, filemode='w', level=logging.DEBUG)
	log_output('[settings] Set up logging to file %s' % SG_LOG_FILE)


def log_symbol_failure(reason=None):
	if reason:
		log_output('Failed to find symbol. Reason: %s' % reason, is_symbol=True)

def log_major_failure(error_callback, text):
	if error_callback:
		error_callback(text)
	logging.error(text)

def log_output(output, log_type='debug', is_symbol=False, is_network=False):
	if LOG_LEVEL == LOG_ALL:
		print(output)
	elif LOG_LEVEL == LOG_NETWORK and is_network:
		print(output)
	elif LOG_LEVEL == LOG_SYMBOLS and is_symbol:
		print(output)
	if log_type == 'debug':
		logging.debug(output)
	elif log_type == 'info':
		logging.info(output)
	elif log_type == 'error':
		logging.error(output)


def parse_import_path(godefinfo_err):
	try:
		return godefinfo_err.split('"')[1]
	except Exception as e:
		log_output('[godefinfo] Error parsing import path: %s' % e.strerror, log_type='error')
		return None


def search_for_symbols(curr_offset, curr_line, row, col, enable_lookback):
	if enable_lookback is True:
		look_back_str = curr_line[:col]
		if look_back_str.endswith('('):
			return curr_offset - 1
		elif look_back_str.endswith(')'):
			last_index_in_row = curr_line[:col].rfind('(')
			if last_index_in_row == -1:
				return curr_offset
			return curr_offset - (col - last_index_in_row)
	return curr_offset

def get_go_version(out, err):
	if err:
		return None
	else:
		out = out.replace('go version go', '')
		version = float(out[0:3])
		return version

def check_gopath(env):
	# Check that GOPATH exists and is a valid directory
	# TODO why is GOPATH set in the first place? Make sure it is equal to settings.ENV["GOPATH"]
	if 'GOPATH' not in env:
		return ERR_GOPATH_UNDEFINED

	for gopath in get_gopaths(env['GOPATH']):
		try:
			os.listdir(gopath)
		except:
			return ERR_GOPATH_UNDEFINED

def check_go(settings):
	# Check that we have access to the go binary
	if not settings.GOBIN:
		return ERR_GO_BINARY

	out, err, return_code = run_shell_command([settings.GOBIN, "version"], settings.ENV)
	if return_code != 0:
		return ERR_GO_BINARY

	# Check that the go version is > 1.6
	version = get_go_version(out, err)
	if not version:
		return ERR_GO_VERSION
	elif version < 1.6:
		return ERR_GO_VERSION

def validate_settings(settings):
	# Validate that we have access to a working shell
	if not is_windows() and 'SHELL' not in settings.ENV:
		return ERR_UNRECOGNIZED_SHELL

	if not is_windows():
		out, err, return_code = run_shell_command(['pwd'], settings.ENV)
		if return_code != 0:
			return ERR_UNRECOGNIZED_SHELL

	gopath_err = check_gopath(settings.ENV)
	if gopath_err:
		return gopath_err

	go_err = check_go(settings)
	if go_err:
		return go_err

	# Check that godefinfo is available
	godefinfo_command = ['godefinfo', '-v']
	out, err, return_code = run_shell_command(godefinfo_command, settings.ENV)
	if return_code != 0:
		return ERR_GODEFINFO_INSTALL
