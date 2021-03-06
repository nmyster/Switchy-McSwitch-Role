#!/Users/Neil/.pyenv/shims/python

"""AWS CLI Switch Roles setup."""

import argparse
import boto3
import botocore
import errno
import sys
try:
    from switchy import MFAChameleon
except:
    pass
try:
    import configparser
except Exception:
    import ConfigParser

from botocore.exceptions import ClientError
import os
import json
import datetime
import logging
import inspect

from dateutil.tz import tzutc


class SwitchyMcSwitchRole(object):
    """Main SwitchRole."""

    def __init__(self, config_file='configuration.json'):
        """Init Method."""
        self.current_dir = "/".join(inspect.stack()[0][1].split("/")[:-1])
        self.configuration_file = self.load_config(config_file)
        self.aws_config_parts = self.configuration_file['configuration']['aws_config']
        self.setup_argparse()

        self.setup_logging()

    def setup_logging(self):
        """Setup Logging."""
        # logging.getLogger('boto').setLevel(logging.CRITICAL)
        # logging.getLogger('botocore').setLevel(logging.CRITICAL)
        level = logging.INFO
        if self.passed_arguments.debug:
            level = logging.DEBUG

        self.log = logging.getLogger(__name__)
        self.log.setLevel(level)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "[%(asctime)s] %(module)s::%(funcName)s::%(lineno)d %(message)s"
        )

        handler_debug = logging.StreamHandler(sys.stdout)
        handler_debug.setFormatter(formatter)
        handler_debug.setLevel(logging.DEBUG)
        self.log.addHandler(handler_debug)

    def setup_argparse(self):
        """Setup ArgParse."""
        parser = argparse.ArgumentParser()
        arguments = self.configuration_file['arguments']
        # Check all the arguments passed in
        for a in arguments:
            # Add the argument to the parser
            allow_empty = a.get('empty', None)
            argument_kwords = {
                "required": a['required'],
                "help": a['help']
            }
            if allow_empty:
                argument_kwords['action'] = 'store_true'
            else:
                argument_kwords['metavar'] = '<arg>'
                argument_kwords['type'] = str

            parser.add_argument(
                a['accept'],
                **argument_kwords
            )

            # # Return the parsed arguments
        self.passed_arguments = parser.parse_args()

    def load_config(self, config):
        """Load Config File."""
        parsed = None
        if self.current_dir == "":
            self.current_dir = "."

        with open(self.current_dir + "/" + config) as f:
            parsed = json.load(f)
        return parsed

    def get_new_session(self, sts, serial):
        """Get new STS session token.

        Args:
            sts (boto3.sts.client): the STS client to use
            serial (str): a string for the MFA device to use

        Returns:
            boto3.sts.session_token: can be used to get new role tokens
        """
        try:
            if self.passed_arguments.mfa:
                mfa = self.passed_arguments.mfa
            else:
                try:
                    mfa = MFAChameleon(account=self.passed_arguments.profile).main()
                except:
                    mfa = input(
                        "What is your MFA code for {}? ".format(
                            self.passed_arguments.profile
                        )
                    )

            session_token = sts.get_session_token(
                DurationSeconds=10800,
                SerialNumber=serial,
                TokenCode=mfa
            )
            return session_token
        except ClientError:
            self.log.info("MFA Code is not valid")
            quit()

    def get_config_files(self):
        """Get Config files."""
        self.paths = {
            "config": "~/.aws/config",
            "creds": "~/.aws/credentials"
        }

        try:
            self.aws_config = ConfigParser.ConfigParser()
            self.aws_credentials = ConfigParser.ConfigParser()
        except NameError:
            self.aws_config = configparser.ConfigParser()
            self.aws_credentials = configparser.ConfigParser()

        config_file_path = os.path.expanduser(self.paths['config'])
        self.aws_config.read([config_file_path])

        credentials_file_path = os.path.expanduser(self.paths['creds'])
        self.aws_credentials.read([credentials_file_path])

    def main(self):
        """Main CLI process."""
        try:
            self.get_config_files()
            if not self.passed_arguments.list:
                self.aws_config = self.update_aws_config(
                    "default",
                    self.aws_config,
                    "profile " + self.passed_arguments.name,
                    self.aws_config
                )

                role_got = False
                s = boto3.session.Session(
                    profile_name=self.passed_arguments.profile
                )
                try:
                    account = s.client('sts').get_caller_identity()['Account']
                except Exception as e:
                    account = str(e).split('::')[2].split(":")[0]

                serial = "arn:aws:iam::{}:mfa/{}".format(
                    account, self.passed_arguments.username
                )
                self.aws_config = self.update_aws_config(
                    "config",
                    self.aws_config,
                    "profile " + self.passed_arguments.name,
                    ""
                )

                sts = None
                role_token = None
                to_check = 'switch-role ' + self.passed_arguments.profile

                if self.aws_credentials.has_section(to_check):

                    if self.aws_credentials.has_option(
                        to_check, 'aws_session_token'
                    ):
                        try:
                            self.sts = s.client(
                                'sts',
                                aws_access_key_id=self.aws_credentials.get(
                                    to_check, 'aws_access_key_id'
                                ),
                                aws_secret_access_key=self.aws_credentials.get(
                                    to_check, 'aws_secret_access_key'
                                ),
                                aws_session_token=self.aws_credentials.get(
                                    to_check, 'aws_session_token'
                                )
                            )
                            role_token = self.get_role(
                                profile=self.passed_arguments
                            )
                            if role_token:
                                role_got = True
                                self.log.debug("Role retrieved")
                        except Exception as e:
                            self.log.error(e)
                            pass

                self.write_aws_config(
                    self.aws_config, config_file=self.paths['config']
                )
                if not role_got:
                    sts = s.client('sts')
                    session_token = self.get_new_session(sts, serial)

                    self.sts = s.client(
                        'sts',
                        aws_access_key_id=session_token['Credentials']['AccessKeyId'],
                        aws_secret_access_key=session_token['Credentials']['SecretAccessKey'],
                        aws_session_token=session_token['Credentials']['SessionToken']
                    )

                    self.write_aws_config(
                        self.aws_config, config_file=self.paths['config']
                    )

                    self.aws_credentials = self.update_aws_config(
                        "credentials",
                        self.aws_credentials,
                        "switch-role " + self.passed_arguments.profile,
                        session_token
                    )

                role_token = self.get_role(profile=self.passed_arguments)

                self.aws_credentials = self.update_aws_config(
                    "credentials",
                    self.aws_credentials,
                    self.passed_arguments.name,
                    role_token
                )

                # load arguments
                # see whats in use already
                self.write_aws_config(
                    self.aws_credentials,
                    config_file=self.paths['creds']
                )

                self.log.info(
                    """Switch role completed - You can now use --profile {} \
in your aws cli commands or in AWS API's""".format(
                        self.passed_arguments.name
                    )
                )

            else:
                if self.passed_arguments.all:
                    self.log.info("Listing All Profiles")
                else:
                    self.log.info("Listing Valid Profiles")

                expired = []
                valid = []
                for section in self.aws_config.sections():
                    if "profile" in section:
                        if self.aws_credentials.has_section(section[8:]):
                            if self.aws_credentials.has_option(
                                section[8:], 'token_expiration'
                            ):
                                expire = datetime.datetime.strptime(
                                    self.aws_credentials.get(
                                        section[8:], 'token_expiration'
                                    ),
                                    '%Y-%m-%d %H:%M:%S+00:00') + datetime.timedelta(
                                    hours=1
                                )
                                now = datetime.datetime.now()
                                if now > expire:
                                    msg = "\033[91mExpired\033[00m"
                                    expired.append(
                                        "{} | {}".format(msg, section[8:])
                                    )
                                else:
                                    diff = int((expire - now).seconds / 60)
                                    if diff < 15:
                                        msg = "\033[33m{} minutes remaining\
                                         \033[00m".format(diff)
                                    else:
                                        msg = "\033[92m{} minutes remaining \
                                        \033[00m".format(diff)

                                    valid.append(
                                        "{} | {}".format(msg, section[8:])
                                    )

                if self.passed_arguments.all:
                    for n in expired:
                        self.log.info(n)

                for i in valid:
                    self.log.info(i)
        except Exception as e:
            self.log.info(e)

    def write_aws_config(self, aws_config, config_file):
        """Write updates to the Config object in the specified file."""
        self.log.debug("Writing file " + config_file)

        config_file_path = os.path.expanduser(config_file)
        with open(config_file_path, 'w+') as fh:
            aws_config.write(fh)

    def get_role(self, profile=None):
        """Return a new role from STS.

        Args:
            profile (dict, optional): Profile tuple that contains info needed

        Returns:
            boto3.sts.assumed_role: Used later
        """
        self.log.debug(profile)
        arg_list = {
            "RoleArn": 'arn:aws:iam::{}:role/{}'.format(
                self.passed_arguments.account,
                self.passed_arguments.role
            ),
            "RoleSessionName": 'SwitchRole',
            "DurationSeconds": 3600
        }
        self.log.debug(arg_list)
        if profile.external_id:
            arg_list['ExternalId'] = profile.external_id
        try:
            return self.sts.assume_role(**arg_list)
        except botocore.exceptions.ClientError as e:
            self.log.debug(e)
            return None

    def mkdir_p(self, path):
        """Make Directory."""
        try:
            os.makedirs(path)
        except OSError as exc:  # Python >2.5
            if exc.errno == errno.EEXIST and os.path.isdir(path):
                pass
            else:
                raise

    def get_input(self, ask_text):
        """Get User input. Python 2/3 friendly."""
        try:
            return raw_input(ask_text)
        except NameError:
            return input(ask_text)

    def update_aws_config(
            self,
            part,
            configuration,
            profile,
            config_update,
            default_region='eu-west-1'):
        """Update Config object with passed in details."""
        # Check if part to update is config or creds

        self.log.debug(part)
        self.log.debug(profile)
        argument_dict = vars(self.passed_arguments)
        if part == "default":

            if configuration.has_section(profile) and \
               configuration.has_option(profile, "profile"):
                self.passed_arguments.profile = configuration.get(profile, "profile")

            if not configuration.has_section("switch-role"):
                configuration.add_section("switch-role")

            for config_part, config in self.aws_config_parts['default'].items():
                # if argument not provided but in config
                argument = argument_dict[config['arg']]

                if not argument and configuration.has_option(
                    "switch-role",
                    config_part
                ):
                    argument_dict[config['arg']] = configuration.get("switch-role", config_part)  # set argument to config item
                # elif the argument exists AND config has the option, set the config to be the argument
                elif argument and configuration.has_option("switch-role", config_part):
                    configuration.set("switch-role", config_part, argument)
                # elif argument exists but config DOES NOT have the option, add the option to the config
                elif argument and not configuration.has_option(
                    "switch-role",
                    config_part
                ):
                    configuration.set("switch-role", config_part, argument)
                # if not in config or argument, ask for a value to give
                else:
                    new_value = self.get_input(
                        config['input_text']
                    )
                    argument_dict[config['arg']] = new_value
                    configuration.set("switch-role", config_part, new_value)

        if part == "config":
            if not configuration.has_section(profile):
                self.log.debug("Adding section " + profile)
                configuration.add_section(profile)

            configuration.set(profile, 'output', "json")
            configuration.set(profile, 'region', "eu-west-1")

            for config_part, config in self.aws_config_parts['config'].items():
                argument = argument_dict[config['arg']]
                self.log.debug(configuration.options(profile))
                self.log.debug(argument)
                if not argument and configuration.has_option(profile, config_part):
                    argument_dict[config['arg']] = configuration.get(profile, config_part)
                elif argument and configuration.has_option(profile, config_part):
                    configuration.set(profile, config_part, argument)
                elif argument and not configuration.has_option(profile, config_part):
                    configuration.set(profile, config_part, argument)
                else:

                    input_text = config.get('input_text', None)
                    if input_text:
                        new_value = self.get_input(
                            config['input_text']
                        )
                        argument_dict[config['arg']] = new_value
                        configuration.set(profile, config_part, new_value)

        elif part == "credentials":
            cred_parts = self.configuration_file['configuration']['credential_parts']

            if not configuration.has_section(profile):
                configuration.add_section(profile)
            self.log.debug("We found config update")
            self.log.debug(config_update)
            for part, value in cred_parts.items():

                if config_update:

                    if value == 'Expiration':
                        value = config_update['Credentials'][value].strftime("%Y-%m-%d %H:%M:%S+00:00")
                        configuration.set(profile, part, value)
                    else:
                        configuration.set(profile, part, config_update['Credentials'][value])
        try:
            self.log.debug(configuration.options(profile))
        except:
            pass

        return configuration
SwitchyMcSwitchRole().main()
