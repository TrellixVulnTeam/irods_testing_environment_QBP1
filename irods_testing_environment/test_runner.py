# grown-up modules
import logging
import os
import queue
import time

# local modules
from . import context
from . import execute

class test_runner:
    """A class that manages a list of tests and can execute them on a managed container."""

    def __init__(self, executing_container):
        """Constructor for `test_runner`.

        Arguments:
        executing_container -- the container on which tests will be executed
        """
        # TODO: each test runner is tied to a single container... might need to abstract this out later
        self.executor = executing_container
        self.tests = list()
        self.rc = 0

        # When a test completes - whether passing or failing - it will be associated with an
        # epoch timestamp from the time module representing the time it took to pass or fail.
        # These are stored in two lists of tuples. These are not dicts because if the same test
        # is run multiple times in an executor, there will be naming collisions.
        self.passed = list()
        self.failed = list()

        # Start the duration time at -1 to indicate that no tests have run
        self.duration = -1


    def __str__(self):
        """Return a string representation of a map representing the data members."""
        return str({
            'executing_container': self.name(),
            'return_code': self.rc,
            'test_list': self.tests,
            'passed_tests': self.passed_tests(),
            'failed_tests': self.failed_tests(),
            'duration': self.duration
        })


    def add_test(self, test):
        """Append `test` to the test list and return self."""
        logging.info('before [{}]'.format(self))
        self.tests.append(test)
        logging.info('after  [{}]'.format(self))
        return self


    def name(self):
        """Return the name of the executing container."""
        return self.executor.name


    def test_list(self):
        """Return the list of tests for which this runner is responsible."""
        return self.tests


    def passed_tests(self):
        """Return the list of tests which have been executed and passed."""
        return self.passed


    def failed_tests(self):
        """Return the list of tests which have been executed and failed."""
        return self.failed


    def skipped_tests(self):
        """Return the list of tests which have not been executed."""
        executed_tests = [t for t,_ in self.passed_tests()] + [t for t,_ in self.failed_tests()]
        return list(filter(lambda t: t not in executed_tests, self.test_list()))


    def result_string(self):
        """Return a string representing the results of running the test list."""
        r = '-----\nresults for [{}]\n'.format(self.name())

        r = r + '\tpassed tests:\n'
        for test, duration in self.passed_tests():
            # TODO: a test list of type None may not indicate that all tests ran
            r = r + '\t\t[[{:>9.4f}]s]\t[{}]\n'.format(duration, test or 'all tests')

        r = r + '\tskipped tests:\n'
        for t in self.skipped_tests():
            # TODO: a test list of type None may not indicate that all tests ran
            r = r + '\t\t[{}]\n'.format(t or 'all tests')

        r = r + '\tfailed tests:\n'
        for test, duration in self.failed_tests():
            # TODO: a test list of type None may not indicate that all tests ran
            r = r + '\t\t[[{:>9.4f}]s]\t[{}]\n'.format(duration, test or 'all tests')

        r = r + '\treturn code:[{}]\n'.format(self.rc)

        if self.duration > 0:
            hours = int(self.duration / 60 / 60)
            minutes = self.duration / 60 - hours * 60
            r = r + '\ttime elapsed: [{:9.4}]seconds ([{:4}]hours [{:9.4}]minutes)\n'.format(
                self.duration, hours, minutes)

        r = r + '-----\n'

        return r


    def run(self, test_queue, fail_fast=True, **kwargs):
        """Execute tests from `test_queue` in executing container.

        Arguments:
        test_queue -- the `Queue` tracking the tests being run by the `test_runner`s
        fail_fast -- if True, the first test to fail ends the run
        **kwargs -- keyword arguments for the specific `test_runner` implementation
        """
        run_start = time.time()

        try:
            # TODO: python >=3.8 - Use while t := test_queue.get(block=False):
            while True:
                # TODO: Consider block=True/Queue.join(). May butt heads with current design.
                # Queue.get will raise queue.Empty when there is nothing in the queue.
                t = test_queue.get(block=False)
                self.add_test(t)

                logging.warning(f'[{self.name()}]: running test [{t}]')

                start = time.time()

                cmd, ec = self.execute_test(t, **kwargs)

                end = time.time()

                test_queue.task_done()

                duration = end - start

                logging.info(f'[{self.name()}]: cmd [{ec}] [{cmd}]')

                if ec is 0:
                    self.passed_tests().append((t, duration))
                    logging.error(f'[{self.name()}]: test passed [[{duration:>9.4f}]s] [{t or "all tests"}]')

                else:
                    self.rc = ec
                    self.failed_tests().append((t, duration))
                    logging.error(f'[{self.name()}]: test failed [[{duration:>9.4f}]s] [{t or "all tests"}]')

                    if fail_fast:
                        raise RuntimeError(f'[{self.name()}]: command failed [{cmd}]')

        except queue.Empty:
            logging.info(f'[{self.name()}]: Queue is empty!')

        run_end = time.time()

        self.duration = run_end - run_start

        if self.rc is not 0:
            logging.error('[{}]: tests that failed [{}]'.format(self.name(), self.failed_tests()))


    def execute_test(self, test, **kwargs):
        """Execute `test` with return the command run and the return code."""
        raise NotImplementedError('test_runner is a base class and should not be used directly')


class test_runner_irods_python_suite(test_runner):
    def __init__(self, executing_container):
        super(test_runner_irods_python_suite, self).__init__(executing_container)


    @staticmethod
    def run_tests_command(container):
        """Return a list of strings used as a space-delimited invocation of the test runner."""
        from . import container_info
        return [container_info.python(container), context.run_tests_script()]


    def execute_test(self, test, options=None):
        """Execute `test` with `options` and return the command run and the return code.

        If `test` is `None`, the entire test suite will be run serially using the option
        `--run_specific_test` from the `run_tests.py` script.

        Arguments:
        test -- name of the test to execute
        options -- list of strings which will be appended to the command to execute
        """
        cmd = self.run_tests_command(self.executor)

        cmd.extend(['--run_python_suite'] if test is None else ['--run_specific_test', test])

        if options: cmd.extend(options)

        return cmd, execute.execute_command(self.executor,
                                            ' '.join(cmd),
                                            user='irods',
                                            workdir=context.irods_home())


class test_runner_irods_unit_tests(test_runner):
    def __init__(self, executing_container):
        super(test_runner_irods_unit_tests, self).__init__(executing_container)


    def execute_test(self, test, reporter='junit'):
        """Execute `test` and return the command run and the return code.

        If `test` is `None`, a `TypeError` is raised because the test runner requires that a
        specific test be indicated by name.

        Arguments:
        test -- name of the test to execute
        reporter -- Catch2 reporter to use (options: console, compact, junit, xml)
        """
        if test is None:
            raise TypeError('unit tests must be specified by name - try using --tests')

        output_dir = os.path.join(context.irods_home(), 'log')
        output_path = os.path.join(output_dir, f'{test}_{reporter}_report.out')

        cmd = [os.path.join(context.unit_tests(), test),
               '--reporter', reporter,
               '--out', output_path]
        return cmd, execute.execute_command(self.executor,
                                            ' '.join(cmd),
                                            user='irods',
                                            workdir=context.irods_home())


class test_runner_irods_plugin_tests(test_runner):
    def __init__(self, executing_container):
        super(test_runner_irods_plugin_tests, self).__init__(executing_container)


    # TODO: this could likely just be implemented in yet another subclass
    def stage_test_hook_file_from_repo(self, repo_name, branch=None):
        """Run the test hook from the specified git repository.

        Arguments:
        repo_name -- name of the git repo
        branch -- name of the branch to checkout in cloned git repo
        options -- list of strings representing script options to pass to the run_tests.py script
        """
        from . import services
        return os.path.join(
                services.clone_repository_to_container(self.executor, repo_name, branch=branch),
                'irods_consortium_continuous_integration_test_hook.py')


    # TODO: this could likely just be implemented in yet another subclass
    def stage_custom_test_hook_file(self, path_to_test_hook_on_host):
        """Run the local test hook in the container.

        Arguments:
        path_to_test_hook_on_host -- local filesystem path on host machine to test hook
        options -- list of strings representing script options to pass to the run_tests.py script
        """
        from . import archive

        f = os.path.abspath(path_to_test_hook_on_host)

        archive.copy_archive_to_container(self.executor, archive.create_archive([f]))

        return f


    def execute_test(self,
                     test,
                     plugin_repo_name=None,
                     plugin_branch=None,
                     path_to_test_hook_on_host=None,
                     options=None):
        """Execute `test` and return the command run and the return code.

        If `test` is `None`, the test hook will be run without any options. This is an
        implementation detail of each plugin-specific test hook. In general, the plugins
        usually have a test file packaged with them which is the specific test invoked by
        default.

        Arguments:
        test -- name of the test to execute
        plugin_repo_name -- name of the git repo hosting the plugin test hook
        plugin_branch -- name of the branch of the git repo for desired test hook
        path_to_test_hook_on_host -- path to test hook file on the host
        options -- list of strings which will be appended to the command to execute
        """
        from . import container_info

        if path_to_test_hook_on_host:
            path_to_test_hook_in_container = self.stage_custom_test_hook_file(path_to_test_hook_on_host)
        else:
            path_to_test_hook_in_container = self.stage_test_hook_file_from_repo(plugin_repo_name, plugin_branch)

        cmd = [container_info.python(self.executor), path_to_test_hook_in_container]

        if test is not None:
            cmd.extend(['--test', test])

            if test != self.tests[0]:
                cmd.append('--skip-setup')

        # Install irods_python_ci_utilities for the first test to run on this executor. This
        # will be true even if None is the test being run.
        if len(self.passed_tests()) == 0 and len(self.failed_tests()) == 0:
            from .install import install

            install.install_pip_package_from_repo(self.executor,
                                                  'irods_python_ci_utilities',
                                                  url_base='https://github.com/irods',
                                                  branch='main')

        if options: cmd.extend(options)

        return cmd, execute.execute_command(self.executor, ' '.join(cmd))
