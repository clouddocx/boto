# Copyright (c) 2006,2007 Mitch Garnaat http://garnaat.org/
# Copyright (c) 2011 Chris Moyer http://coredumped.org/
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
#
import StringIO, os, re
import warnings
import ConfigParser
import boto

# If running in Google App Engine there is no "user" and
# os.path.expanduser() will fail. Attempt to detect this case and use a
# no-op expanduser function in this case.
try:
  os.path.expanduser('~')
  expanduser = os.path.expanduser
except (AttributeError, ImportError):
  # This is probably running on App Engine.
  expanduser = (lambda x: x)

# By default we use two locations for the boto configurations,
# /etc/boto.cfg and ~/.boto (which works on Windows and Unix).
BotoConfigPath = '/etc/boto.cfg'
BotoConfigLocations = [BotoConfigPath]
UserConfigPath = os.path.join(expanduser('~'), '.boto')
BotoConfigLocations.append(UserConfigPath)

# If there's a BOTO_CONFIG variable set, we load ONLY
# that variable
if 'BOTO_CONFIG' in os.environ:
    BotoConfigLocations = [expanduser(os.environ['BOTO_CONFIG'])]

# If there's a BOTO_PATH variable set, we use anything there
# as the current configuration locations, split with colons
elif 'BOTO_PATH' in os.environ:
    BotoConfigLocations = []
    for path in os.environ['BOTO_PATH'].split(":"):
        BotoConfigLocations.append(expanduser(path))


class Config(ConfigParser.SafeConfigParser):

    def __init__(self, path=None, fp=None, do_load=True):
        ConfigParser.SafeConfigParser.__init__(self, {'working_dir' : '/mnt/pyami',
                                                      'debug' : '0'})
        if do_load:
            if path:
                self.load_from_path(path)
            elif fp:
                self.readfp(fp)
            else:
                self.read(BotoConfigLocations)
                self.possibly_hide_credentials()
            if "AWS_CREDENTIAL_FILE" in os.environ:
                full_path = expanduser(os.environ['AWS_CREDENTIAL_FILE'])
                try:
                    self.load_credential_file(full_path)
                except IOError:
                    warnings.warn('Unable to load AWS_CREDENTIAL_FILE (%s)' % full_path)

    def possibly_hide_credentials(self):
        """
        If the Credentials:do_not_store_credentials flag is set, blank out the credentials
        from the returned config object and re-read them from the config file in the get
        command when needed. In this way, if you have an open python interpreter and you
        remove a keyfob with your credentials on it when you shutdown for the night, your
        session can't be used to do something possibly sinister with AWS, should you loose
        your laptop, until you re-insert your keyfob.
        """
        # Note, the following calls are all Config.set(self... istead of self.get(... because,
        # in the case of ServiceDef which extends this class, the passed in self reference
        # points to a ServiceDef object which means the wrong get function is called. We want
        # this parent get function, not the get from the chile ServiceDef class.
        if Config.get(self, 'Credentials', 'do_not_store_credentials') == 'True':
            Config.set(self, 'Credentials', 'aws_access_key_id', 'hidden_per_the_setting_do_not_store_credentials')
            Config.set(self, 'Credentials', 'aws_secret_access_key', 'hidden_per_the_setting_do_not_store_credentials')

    def load_credential_file(self, path):
        """Load a credential file as is setup like the Java utilities"""
        c_data = StringIO.StringIO()
        c_data.write("[Credentials]\n")
        for line in open(path, "r").readlines():
            c_data.write(line.replace("AWSAccessKeyId", "aws_access_key_id").replace("AWSSecretKey", "aws_secret_access_key"))
        c_data.seek(0)
        self.readfp(c_data)

    def load_from_path(self, path):
        file = open(path)
        for line in file.readlines():
            match = re.match("^#import[\s\t]*([^\s^\t]*)[\s\t]*$", line)
            if match:
                extended_file = match.group(1)
                (dir, file) = os.path.split(path)
                self.load_from_path(os.path.join(dir, extended_file))
        self.read(path)

    def save_option(self, path, section, option, value):
        """
        Write the specified Section.Option to the config file specified by path.
        Replace any previous value.  If the path doesn't exist, create it.
        Also add the option the the in-memory config.
        """
        config = ConfigParser.SafeConfigParser()
        config.read(path)
        if not config.has_section(section):
            config.add_section(section)
        config.set(section, option, value)
        fp = open(path, 'w')
        config.write(fp)
        fp.close()
        if not self.has_section(section):
            self.add_section(section)
        self.set(section, option, value)

    def save_user_option(self, section, option, value):
        self.save_option(UserConfigPath, section, option, value)

    def save_system_option(self, section, option, value):
        self.save_option(BotoConfigPath, section, option, value)

    def get_instance(self, name, default=None):
        try:
            val = self.get('Instance', name)
        except:
            val = default
        return val

    def get_user(self, name, default=None):
        try:
            val = self.get('User', name)
        except:
            val = default
        return val

    def getint_user(self, name, default=0):
        try:
            val = self.getint('User', name)
        except:
            val = default
        return val

    def get_value(self, section, name, default=None):
        return self.get(section, name, default)

    def get(self, section, name, default=None):
        try:
           val = ConfigParser.SafeConfigParser.get(self, section, name)
           #--
           #--- If we're not storing credentials, val won't have the correct info for aws*key names
           #--  Look them up special...
           #--
           if self.has_option('Credentials', 'do_not_store_credentials') and \
                    ConfigParser.SafeConfigParser.get(self, 'Credentials', 'do_not_store_credentials') == 'True':
                if section == 'Credentials' and name == 'aws_access_key_id':
                    local_config_parser = ConfigParser.SafeConfigParser({'working_dir' : '/tmp', 'debug' : 0})
                    local_config_parser.read(BotoConfigLocations)
                    val = local_config_parser.get('Credentials', 'aws_access_key_id')
                if section == 'Credentials' and name == 'aws_secret_access_key':
                    local_config_parser = ConfigParser.SafeConfigParser({'working_dir' : '/tmp', 'debug' : 0})
                    local_config_parser.read(BotoConfigLocations)
                    val = local_config_parser.get('Credentials', 'aws_secret_access_key')
        except:
            val = default
        return val

    def getint(self, section, name, default=0):
        try:
            val = ConfigParser.SafeConfigParser.getint(self, section, name)
        except:
            val = int(default)
        return val

    def getfloat(self, section, name, default=0.0):
        try:
            val = ConfigParser.SafeConfigParser.getfloat(self, section, name)
        except:
            val = float(default)
        return val

    def getbool(self, section, name, default=False):
        if self.has_option(section, name):
            val = self.get(section, name)
            if val.lower() == 'true':
                val = True
            else:
                val = False
        else:
            val = default
        return val

    def setbool(self, section, name, value):
        if value:
            self.set(section, name, 'true')
        else:
            self.set(section, name, 'false')

    def dump(self):
        s = StringIO.StringIO()
        self.write(s)
        print s.getvalue()

    def dump_safe(self, fp=None):
        if not fp:
            fp = StringIO.StringIO()
        for section in self.sections():
            fp.write('[%s]\n' % section)
            for option in self.options(section):
                if option == 'aws_secret_access_key':
                    fp.write('%s = xxxxxxxxxxxxxxxxxx\n' % option)
                else:
                    fp.write('%s = %s\n' % (option, self.get(section, option)))

    def dump_to_sdb(self, domain_name, item_name):
        try:
            import simplejson as json
        except ImportError:
            import json

        sdb = boto.connect_sdb()
        domain = sdb.lookup(domain_name)
        if not domain:
            domain = sdb.create_domain(domain_name)
        item = domain.new_item(item_name)
        item.active = False
        for section in self.sections():
            d = {}
            for option in self.options(section):
                d[option] = self.get(section, option)
            item[section] = json.dumps(d)
        item.save()

    def load_from_sdb(self, domain_name, item_name):
        try:
            import json
        except ImportError:
            import simplejson as json

        sdb = boto.connect_sdb()
        domain = sdb.lookup(domain_name)
        item = domain.get_item(item_name)
        for section in item.keys():
            if not self.has_section(section):
                self.add_section(section)
            d = json.loads(item[section])
            for attr_name in d.keys():
                attr_value = d[attr_name]
                if attr_value == None:
                    attr_value = 'None'
                if isinstance(attr_value, bool):
                    self.setbool(section, attr_name, attr_value)
                else:
                    self.set(section, attr_name, attr_value)
