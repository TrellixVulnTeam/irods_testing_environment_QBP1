# grown-up modules
import compose.cli.command
import docker
import json
import logging
import os

# local modules
from . import context
from . import execute
from . import json_utils

# This dict maps container names to iRODS zone names so that the name of the zone of the iRODS
# server being run by each container is cached for easy access at any time. This is only meant to
# be used by get_irods_zone_name and is declared here to extend the lifetime of the dict.
irods_zone = dict()

# This dict maps container names to iRODS version triples so that the version of iRODS being run
# by each container is cached for easy access at any time. This is only meant to be used by
# get_irods_version and is declared here to extend the lifetime of the dict.
irods_version = dict()

def get_irods_zone_name(container):
    """Return the Zone name of the iRODS server running on `container`."""
    global irods_zone

    # If we have the iRODS version cached for this container, return that.
    if container.name in irods_zone:
        return irods_zone[container.name]

    irods_zone[container.name] = json_utils.get_json_from_file(
            container, context.server_config())['zone_name']

    return irods_zone[container.name]


def get_irods_version(container):
    """Return the version of iRODS running on `container` as a tuple (major, minor, patch)."""
    global irods_version

    # If we have the iRODS version cached for this container, return that.
    if container.name in irods_version:
        return irods_version[container.name]

    # The name of the version file changed in iRODS version 4.3.0. The testing environment supports
    # both 4.3.x and 4.2.x versions, so we want to check for both file names.
    version_file_locations = [
            os.path.join(context.irods_home(), 'version.json.dist'),
            os.path.join(context.irods_home(), 'VERSION.json.dist')
    ]

    for f in version_file_locations:
        # Check to see whether the file exists. If not, try the next one.
        if execute.execute_command(container, f'bash -c "[[ -f {f} ]]"') != 0:
            logging.debug(f'[{container.name}]: version file [{f}] not found')
            continue

        logging.debug(f'[{container.name}]: version file [{f}] found')

        # If the file exists, extract the version string and store it in the version
        # dictionary under this container's name.
        irods_version[container.name] = tuple(int(i) for i in
            json_utils.get_json_from_file(container, f)['irods_version']
            .split('.'))

        return irods_version[container.name]

    # If we reach here, that's no good.
    raise RuntimeError(f'[{container.name}]: No iRODS version file found')


def configure_users_for_auth_tests(docker_client, compose_project):
    """Create Linux users and set passwords for authentication testing.

    Arguments:
    docker_client -- docker client for interacting with the docker-compose project
    compose_project -- compose.Project in which the iRODS servers are running
    usernames_and_passwords -- a list of tuples of usernames/passwords (passwords can be empty)
    """
    def create_test_users(docker_client, docker_compose_container, usernames_and_passwords):
        container = docker_client.containers.get(docker_compose_container.name)

        for username, password in usernames_and_passwords:
            create_user = f'useradd {username}'

            if execute.execute_command(container, create_user) is not 0:
                raise RuntimeError(f'[{container.name}] failed to create user [{username}]')

            if password is None or password == '':
                continue

            set_password = f'bash -c "echo \'{username}:{password}\' | chpasswd"'

            if execute.execute_command(container, set_password) is not 0:
                raise RuntimeError(f'[{container.name}] failed to create hosts_config file')

        return 0

    import concurrent.futures

    containers = compose_project.containers(service_names=[
        context.irods_catalog_provider_service(),
        context.irods_catalog_consumer_service()])

    rc = 0
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # TODO: get these names from the test file packaged with the server
        usernames_and_passwords = [
            ('irodsauthuser', ';=iamnotasecret')
        ]

        futures_to_containers = {
            executor.submit(
                create_test_users, docker_client, c, usernames_and_passwords
            ): c for c in containers
        }

        logging.debug(futures_to_containers)

        for f in concurrent.futures.as_completed(futures_to_containers):
            container = futures_to_containers[f]
            try:
                ec = f.result()
                if ec is not 0:
                    logging.error(f'[{container.name}] error while creating test user accounts')
                    rc = ec
                else:
                    logging.info(f'[{container.name}] successfully created test user accounts')

            except Exception as e:
                logging.error(f'[{container.name}] exception raised while creating test users')
                logging.error(e)
                rc = 1

    if rc is not 0:
        raise RuntimeError('failed to create test user accounts on some service')


def configure_hosts_config(docker_client, compose_project):
    """Set hostname aliases for all iRODS servers in the compose project via hosts_config.json.

    Arguments:
    docker_client -- docker client for interacting with the docker-compose project
    compose_project -- compose.Project in which the iRODS servers are running
    """
    def set_hostnames(docker_client, docker_compose_container, hosts_file):
        container = docker_client.containers.get(docker_compose_container.name)

        if context.is_irods_catalog_provider_container(container):
            alias = 'icat.example.org'
        else:
            alias = 'resource{}.example.org'.format(
                context.service_instance(docker_compose_container.name))

        hosts = {
            'host_entries': [
                {
                    'address_type': 'local',
                    'addresses': [
                        {'address': context.container_hostname(container)},
                        {'address': context.container_ip(container)},
                        {'address': alias}
                    ]
                }
            ]
        }

        for o in containers:
            if o.name == container.name: continue

            other = docker_client.containers.get(o.name)

            if context.is_irods_catalog_provider_container(other):
                remote_address = 'icat.example.org'
            else:
                remote_address = 'resource{}.example.org'.format(
                    context.service_instance(other.name))

            hosts['host_entries'].append(
                {
                    'address_type': 'remote',
                    'addresses': [
                        {'address': context.container_ip(other)},
                        {'address': context.container_hostname(other)},
                        {'address': remote_address}
                    ]
                }
            )

        logging.info('json for hosts_config [{}] [{}]'.format(json.dumps(hosts), container.name))

        create_hosts_config = 'bash -c \'echo "{}" > {}\''.format(
            json.dumps(hosts).replace('"', '\\"'), hosts_file)

        if execute.execute_command(container, create_hosts_config) is not 0:
            raise RuntimeError('failed to create hosts_config file [{}]'.format(container.name))

        return 0

    import concurrent.futures

    containers = compose_project.containers(service_names=[
        context.irods_catalog_provider_service(),
        context.irods_catalog_consumer_service()])

    rc = 0
    with concurrent.futures.ThreadPoolExecutor() as executor:
        hosts_file = os.path.join('/etc', 'irods', 'hosts_config.json')
        futures_to_containers = {
            executor.submit(set_hostnames, docker_client, c, hosts_file): c for c in containers
        }
        logging.debug(futures_to_containers)

        for f in concurrent.futures.as_completed(futures_to_containers):
            container = futures_to_containers[f]
            try:
                ec = f.result()
                if ec is not 0:
                    logging.error('error while configuring hosts_configs.json on container [{}]'
                                  .format(container.name))
                    rc = ec
                else:
                    logging.info('hosts_config.json configured successfully [{}]'
                                 .format(container.name))

            except Exception as e:
                logging.error('exception raised while installing packages [{}]'
                              .format(container.name))
                logging.error(e)
                rc = 1

    if rc is not 0:
        raise RuntimeError('failed to configure hosts_config.json on some service')


def configure_univmss_script(docker_client, compose_project):
    """Configure UnivMSS script for iRODS tests.

    Arguments:
    docker_client -- docker client for interacting with the docker-compose project
    compose_project -- compose.Project in which the iRODS servers are running
    """
    def modify_script(docker_client, docker_compose_container, script):
        chown_msiexec = 'chown irods:irods {}'.format(os.path.dirname(univmss_script))
        copy_from_template = 'cp {0}.template {0}'.format(univmss_script)
        remove_template_from_commands = 'sed -i \"s/template-//g\" {}'.format(univmss_script)
        make_script_executable = 'chmod 544 {}'.format(univmss_script)

        on_container = docker_client.containers.get(docker_compose_container.name)
        if execute.execute_command(on_container, chown_msiexec) is not 0:
            raise RuntimeError('failed to change ownership to msiExecCmd_bin [{}]'
                               .format(on_container.name))

        if execute.execute_command(on_container,
                                   copy_from_template,
                                   user='irods',
                                   workdir=context.irods_home()) is not 0:
            raise RuntimeError('failed to copy univMSSInterface.sh template file [{}]'
                               .format(on_container.name))

        if execute.execute_command(on_container,
                                   remove_template_from_commands,
                                   user='irods',
                                   workdir=context.irods_home()) is not 0:
            raise RuntimeError('failed to modify univMSSInterface.sh template file [{}]'
                               .format(on_container.name))

        if execute.execute_command(on_container,
                                   make_script_executable,
                                   user='irods',
                                   workdir=context.irods_home()) is not 0:
            raise RuntimeError('failed to change permissions on univMSSInterface.sh [{}]'
                               .format(on_container.name))

        return 0

    import concurrent.futures

    containers = compose_project.containers(service_names=[
        context.irods_catalog_provider_service(),
        context.irods_catalog_consumer_service()])

    rc = 0
    with concurrent.futures.ThreadPoolExecutor() as executor:
        univmss_script = os.path.join(
            context.irods_home(), 'msiExecCmd_bin', 'univMSSInterface.sh')

        futures_to_containers = {
            executor.submit(
                modify_script, docker_client, c, univmss_script
            ): c for c in containers
        }

        logging.debug(futures_to_containers)

        for f in concurrent.futures.as_completed(futures_to_containers):
            container = futures_to_containers[f]
            try:
                ec = f.result()
                if ec is not 0:
                    logging.error('error while configuring univMSS script on container [{}]'
                                  .format(container.name))
                    rc = ec
                else:
                    logging.info('univMSS script configured successfully [{}]'.format(container.name))

            except Exception as e:
                logging.error('exception raised while configuring univMSS script [{}]'.format(container.name))
                logging.error(e)
                rc = 1

    if rc is not 0:
        raise RuntimeError('failed to configure univMSS script on some service')


def configure_irods_testing(docker_client, compose_project):
    """Run a series of prerequisite configuration steps for iRODS tests.

    Arguments:
    docker_client -- docker client for interacting with the docker-compose project
    compose_project -- compose.Project in which the iRODS servers are running
    """
    configure_hosts_config(docker_client, compose_project)

    configure_univmss_script(docker_client, compose_project)

    configure_users_for_auth_tests(docker_client, compose_project)


def configure_irods_federation_testing(ctx, remote_zone, zone_where_tests_will_run):
    """Configure iRODS Zones to run the federation test suite.

    Arguments:
    ctx -- the context object which contains the Docker client and Compose project information
    remote_zone -- Zone info for what will be considered the "remote" in the tests
    zone_where_tests_will_run -- Zone info for what will be considered "local" in the tests
    """
    container = ctx.docker_client.containers.get(
        context.irods_catalog_provider_container(
            ctx.compose_project.name,
            service_instance=remote_zone.provider_service_instance
        )
    )

    execute.execute_command(container, 'iadmin lu', user='irods')
    execute.execute_command(container, 'iadmin lz', user='irods')

    # create zonehopper user
    username = '#'.join(['zonehopper', zone_where_tests_will_run.zone_name])
    mkuser = 'iadmin mkuser {} rodsuser'.format(username)
    logging.info('creating remote user [{}] [{}]'.format(mkuser, container.name))
    if execute.execute_command(container, mkuser, user='irods') is not 0:
        raise RuntimeError('failed to create remote user [{}] [{}]'
                           .format(username, container.name))

    execute.execute_command(container, 'iadmin lu', user='irods')

    # create passthrough resource
    ptname = 'federation_remote_passthrough'
    make_pt = 'iadmin mkresc {} passthru'.format(ptname)
    logging.info('creating passthrough resource [{}] [{}]'.format(make_pt, container.name))
    if execute.execute_command(container, make_pt, user='irods') is not 0:
        raise RuntimeError('failed to create passthrough resource [{}] [{}]'
                           .format(ptname, container.name))

    # create the storage resource
    ufsname = 'federation_remote_unixfilesystem_leaf'
    make_ufs = 'iadmin mkresc {} unixfilesystem {}:{}'.format(
        ufsname, context.container_hostname(container),
        os.path.join('/tmp', ufsname))
    logging.info('creating unixfilesystem resource [{}] [{}]'.format(make_ufs, container.name))
    if execute.execute_command(container, make_ufs, user='irods') is not 0:
        raise RuntimeError('failed to create unixfilesystem resource [{}] [{}]'
                           .format(ufsname, container.name))

    # make the hierarchy
    make_hier = 'iadmin addchildtoresc {} {}'.format(ptname, ufsname)
    logging.info('creating hierarchy [{}] [{}]'.format(make_hier, container.name))
    if execute.execute_command(container, make_hier, user='irods') is not 0:
        raise RuntimeError('failed to create hierarchy [{};{}] [{}]'
                           .format(ptname, ufsname, container.name))

    # add specific query to the local zone
    bug_3466_query = 'select alias, sqlStr from R_SPECIFIC_QUERY'
    asq = 'iadmin asq \'{}\' {}'.format(bug_3466_query, 'bug_3466_query')
    logging.info('creating specific query[{}] [{}]'.format(asq, container.name))
    if execute.execute_command(container, asq, user='irods') is not 0:
        raise RuntimeError('failed to create specific query [{}] [{}]'
                           .format(bug_3466_query, container.name))
