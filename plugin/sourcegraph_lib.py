import json
import logging
import os
import random
import subprocess
import sys
import time


from threading import Thread
try:
	from urllib.request import Request, urlopen
	from urllib.error import HTTPError
except:
	from urllib2 import Request, urlopen
	from urllib2 import HTTPError

LOG_NONE = 0
LOG_SYMBOLS = 1
LOG_NETWORK = 2
LOG_ALL = 3

LOG_LEVEL = LOG_NONE
SG_LOG_FILE = '/tmp/sourcegraph-sublime.log'


class Error(object):
	def __init__(self, title, description):
		self.title = title
		self.description = description

	def __str__(self):
		return "%s : %s" % (self.title, self.description)

ERR_GOPATH_UNDEFINED = Error('GOPATH Undefined', 'Could not find GOPATH in your shell startup scripts or Sublime settings. Please read the GOPATH section in the Sourcegraph Sublime README https://github.com/sourcegraph/sourcegraph-sublime to learn how to set your GOPATH.')
ERR_GODEFINFO_INSTALL = Error('godefinfo binary not found in your PATH', 'Please read the Installation section in the Sourcegraph Sublime README https://github.com/sourcegraph/sourcegraph-sublime to learn how to install godefinfo.')
ERR_GO_BINARY = Error('Go binary not found in your PATH', 'Please read the GOBIN section in the Sourcegraph Sublime README https://github.com/sourcegraph/sourcegraph-sublime to learn how to set your GOBIN.')
ERR_GO_VERSION = Error('Go version is < 1.6', 'Sourcegraph Sublime only works with Go 1.6 and greater.')
ERR_UNRECOGNIZED_SHELL = Error('Sourcegraph for Sublime can\'t execute commands against your shell', 'Contact Sourcegraph with your OS details, and we\'ll try to deliver Sourcegraph for your OS')

def ERR_SYMBOL_NOT_FOUND(symbol):
	return Error('Could not find symbol "%s".' % symbol, 'Please make sure you have selected a valid symbol, and have all imported packages installed on your computer.')

def run_shell_command(command, env):
	try:
		process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
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
	native_command = [shell_env, '--login', '-l', '-c', command]
	process = subprocess.Popen(native_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	out, err = process.communicate()
	if out:
		out = out.decode().strip().split('\n')[-1]
	if err:
		err = err.decode().strip()
	return out, err, process.returncode

class Sourcegraph(object):
	def __init__(self, settings):
		super(Sourcegraph, self).__init__()
		self.IS_OPENING_CHANNEL = False
		self.HAVE_OPENED_CHANNEL = False
		self.EXPORTED_PARAMS_CACHE = None
		self.settings = settings

		# Thread that checks the state of the variable every couple of milliseconds seconds

	def post_load(self):
		setup_logging()
		error_loading = self.add_gopath_to_path()
		if type(error_loading) is ExportedParams:
			self.send_curl_request(error_loading)
		log_output('[settings] env: %s' % str(self.settings.ENV))

	def on_selection_modified_handler(self, lookup_args):
		validate_output = validate_settings(self.settings)
		if validate_output:
			self.send_curl_request(ExportedParams(Error=validate_output.title, Fix=validate_output.description))
			return
		return_object = self.get_sourcegraph_request(lookup_args.filename, lookup_args.cursor_offset, lookup_args.preceding_selection, lookup_args.selected_token)
		print(return_object)
		if return_object:
			self.send_curl_request(return_object)
		elif not self.settings.AUTO_PROCESS:
			self.send_curl_request(ExportedParams(Error=ERR_SYMBOL_NOT_FOUND(lookup_args.selected_token).title, Fix=ERR_SYMBOL_NOT_FOUND(lookup_args.selected_token).description))

	def get_sourcegraph_request(self, filename, cursor_offset, preceding_selection, selected_token):
		if filename is None or not filename.endswith('go'):
			return None
		if self.settings.ENV.get('GOPATH') == '':
			return ExportedParams(Error=ERR_GOPATH_UNDEFINED.title, Fix=ERR_GOPATH_UNDEFINED.description)

		stderr, godefinfo_output = self.run_godefinfo(filename, cursor_offset, preceding_selection)
		if stderr == b'FileNotFoundError':
			return ExportedParams(Error=ERR_GODEFINFO_INSTALL.title, Fix=ERR_GODEFINFO_INSTALL.description)
		if stderr:
			log_symbol_failure(reason=stderr)
			return None

		godefinfo_parsed = godefinfo_output

		if godefinfo_parsed == '':
			log_symbol_failure(reason='[godefinfo] godefinfo returned nothing.')
			return None

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

		return ExportedParams(Def=symbol_name, Repo=repo_package, Package=repo_package)

	def send_curl_request(self, exported_params):
		if self.EXPORTED_PARAMS_CACHE == exported_params:
			return
		self.EXPORTED_PARAMS_CACHE = exported_params
		if not self.HAVE_OPENED_CHANNEL and self.settings.AUTO_OPEN:
			self.open_channel()
			self.HAVE_OPENED_CHANNEL = True
		post_url = '%s/.api/channel/%s' % (self.settings.SG_BASE_URL, self.settings.SG_CHANNEL)
		self.send_curl_request_network(post_url, exported_params.to_json())

	def send_curl_request_network(self, post_url, json_arguments):
		t = Thread(target=self.send_def_info, args=[post_url, json_arguments])
		t.start()

	def send_def_info(self, post_url, json_arguments):
		log_output('[network] Sending post request params: %s' % str(json_arguments), is_network=True)
		log_output('[network] Sending POST request to URL: %s' % post_url, is_network=True)
		try:
			req = Request(post_url, json_arguments.encode('utf-8'), {'Content-Type': 'application/json'})
			f = urlopen(req)
			status_code = f.getcode()
			log_output('[network] Server responded with code %s' % str(status_code), is_network=True)
			f.close()
		except HTTPError as err:
			if self.settings.AUTO_OPEN and not self.IS_OPENING_CHANNEL:
				self.IS_OPENING_CHANNEL = True
				log_output('[network] Server responded with err code %s, reopening browser.' % str(err.code), is_network=True)
				self.open_channel(hard_refresh=True)
				self.send_curl_request_network(post_url, json_arguments)
				time.sleep(2)
				self.IS_OPENING_CHANNEL = False

	def open_channel_os(self):
		self.get_channel()
		command = ['%s/-/channel/%s' % (self.settings.SG_BASE_URL, self.settings.SG_CHANNEL)]
		if sys.platform.startswith('linux'):
			command.insert(0, 'xdg-open')
		elif sys.platform == 'darwin':
			command.insert(0, 'open')
		else:
			command.insert(0, 'start')
		log_output('[open_channel] Opening channel in browser: %s' % command)
		run_shell_command(command, self.settings.ENV)
		time.sleep(2)

	def open_channel(self, hard_refresh=False):
		if hard_refresh:
			self.HAVE_OPENED_CHANNEL = True

		self.open_channel_os()

	def run_godefinfo(self, filename, cursor_offset, godefinfo_region):
		godefinfo_args = [os.path.join(self.settings.ENV['GOPATH'], "bin", "godefinfo"),  '-i', '-o', cursor_offset, '-f', filename]
		log_output('[godefinfo] Running shell command: %s' % ' '.join(godefinfo_args))

		godefinfo_output = b''
		stderr = None
		try:
			godefinfo_process = subprocess.Popen(godefinfo_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.settings.ENV)
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

	def add_gopath_to_path(self):
		if self.settings.ENV.get('GOPATH') != '' and self.settings.ENV.get('GOPATH'):
			for gopath_loc in self.settings.ENV['GOPATH'].split(os.pathsep):
				self.settings.ENV['PATH'] += os.pathsep + os.path.join(gopath_loc, 'bin')
			return godefinfo_auto_install(self.settings.GOBIN, self.settings.ENV)
		else:
			log_output("[settings] Cannot find GOPATH, notifying error API.")
			return ExportedParams(Error=ERR_GOPATH_UNDEFINED.title, Fix=ERR_GOPATH_UNDEFINED.description)

	def get_channel(self):
		if self.settings.SG_CHANNEL is None:
			self.settings.SG_CHANNEL = '%s-%06x%06x%06x%06x%06x%06x' % \
				(os.environ.get('USER'), random.randrange(16**6), random.randrange(16**6),
					random.randrange(16**6), random.randrange(16**6), random.randrange(16**6), random.randrange(16**6))
		else:
			log_output('Using existing channel: %s' % self.settings.SG_CHANNEL)


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
			if self.__dict__[param]:
				json_params[param] = self.__dict__[param]
		return json.dumps(json_params, ensure_ascii=False)

	def __str__(self):
		return self.to_json()


class Settings(object):
	def __init__(self, **kwds):
		super(Settings, self).__init__()
		self.SG_BASE_URL = 'https://grpc.sourcegraph.com'
		self.ENV = os.environ.copy()
		self.AUTO_OPEN = True
		self.AUTO_PROCESS = True
		self.ENABLE_LOOKBACK = True
		self.SG_CHANNEL = None
		output, err, return_code = run_native_shell_command(self.ENV['SHELL'], ['which', 'go'])
		if return_code == 0 and output:
			self.GOBIN = output
		else:
			self.GOBIN = os.path.join('/usr', 'local', 'go', 'bin', 'go')
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
			if self.__dict__[param]:
				json_params['Action'][param] = self.__dict__[param]
		return json.dumps(json_params, ensure_ascii=False)

	def __str__(self):
		return self.to_json()


def godefinfo_auto_install(gobin, env):
	godefinfo_install_command = [gobin, 'get', '-u', 'github.com/sqs/godefinfo']
	log_output('[godefinfo] Settings reloaded, installing godefinfo: %s' % ' '.join(godefinfo_install_command))
	out, err, return_code = run_shell_command(godefinfo_install_command, env)
	if return_code != 0:
		log_symbol_failure(reason='Godefinfo auto-install failure: %s' % str(err))
		return ExportedParams(Error=ERR_GO_BINARY.title, Fix=ERR_GO_BINARY.description)
	return None


def setup_logging():
	logging.basicConfig(filename=SG_LOG_FILE, filemode='w', level=logging.DEBUG)
	log_output('[settings] Set up logging to file %s' % SG_LOG_FILE)


def log_symbol_failure(reason=None):
	if reason:
		log_output('Failed to find symbol. Reason: %s' % reason, is_symbol=True)


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

def get_go_version(env, gobin):
	out, err, return_code = run_shell_command([gobin, "version"], env)
	if err:
		return None
	else:
		out = out.replace('go version go', '')
		version = float(out[0:3])
		return version


def validate_settings(settings):
	# Validate that we have access to a working shell
	if 'SHELL' not in settings.ENV:
		return ERR_UNRECOGNIZED_SHELL

	out, err, return_code = run_shell_command(['pwd'], settings.ENV)
	if return_code != 0:
		return ERR_UNRECOGNIZED_SHELL

	# Check that GOPATH exists and is a valid directory
	# TODO why is GOPATH set in the first place? Make sure it is equal to settings.ENV["GOPATH"]
	if 'GOPATH' not in settings.ENV:
		return ERR_GOPATH_UNDEFINED

	out, err, return_code = run_shell_command(["ls", settings.ENV['GOPATH']], settings.ENV)
	if return_code != 0:
		return ERR_GOPATH_UNDEFINED

	# Check that we have access to the go binary
	if not settings.GOBIN:
		return ERR_GO_BINARY

	out, err, return_code = run_shell_command([settings.GOBIN, "version"], settings.ENV)
	if return_code != 0:
		return ERR_GO_BINARY

	# Check that the go version is > 1.6
	version = get_go_version(settings.ENV, settings.GOBIN)
	if not version:
		return ERR_GO_VERSION
	elif version < 1.6:
		return ERR_GO_VERSION

	# Check that godefinfo is available
	godefinfo_command = [os.path.join(settings.ENV['GOPATH'], 'bin', 'godefinfo'), "-v"]
	out, err, return_code = run_shell_command(godefinfo_command, settings.ENV)
	if return_code != 0:
		return ERR_GODEFINFO_INSTALL

