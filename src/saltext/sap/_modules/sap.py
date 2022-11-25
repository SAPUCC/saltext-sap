"""
SaltStack extension for SAP
Copyright (C) 2022 SAP UCC Magdeburg

SAP general functionality execution module
==========================================
SaltStack execution module for general SAP system control.

:codeauthor:    Alexander Wilke, Benjamin Wegener
:maturity:      new
:depends:       requests sap_hostctrl sap_control
:platform:      All

This module implements functions for controlling SAP systems.
"""
import logging

import salt.utils.dictupdate
import salt.utils.http

# from urllib3.exceptions import NewConnectionError

# Third Party libs
REQUESTSLIB = True
try:
    import requests
    from requests.exceptions import RequestException
except ImportError:
    REQUESTSLIB = False

# Globals
log = logging.getLogger(__name__)

__virtualname__ = "sap"


def __virtual__():
    """
    only load this module if all libraries are available
    """
    if not REQUESTSLIB:
        return False, "Could not load module, requests unavailable"
    return __virtualname__


# pylint: disable=unused-argument
def get_system_data(sid, username, password, verify=True, **kwargs):
    """
    Retrieves information about an SAP system installed on the host. The function
    returns a dictionary with system information. The information retrieved
    depends on the system type.

    .. note::
        Requires ``service/admin_users = <username>`` in *every* instance profile or in the ``DEFAULT`` profile
        of the SAP System.

    .. note::
        Requires ``service/admin_users = <username>`` in the SAP Host Agent profile if ``username`` != ``sapadm``.

    sid
        ID of system to get.

    username
        User for authentication, i.e. ``sapadm``.

    password
        Password for authentication.

    verify
        Verify SSL connection, default is ``True``.

    CLI Example:

    .. code-block:: bash

        salt "*" sap.get_system_data sid="S4H" username="sapadm" password="Abcd1234!"
    """
    log.debug("Running function")
    system_data = {}
    fallback = not verify
    log.debug(f"Getting instances for system {sid}")
    instances = __salt__["sap_hostctrl.list_instances"](
        sid=sid, username=username, password=password, fallback=fallback
    )
    if not instances:
        fqdn = __grains__["fqdn"]
        msg = f"No instances found for {sid} on {fqdn}"
        log.warning(f"{msg}")
        return system_data
    log.debug(f"Got instances\n{instances}")
    system_data = {"instances": {}}

    hostname = next(iter(instances[0]))
    log.debug(f"Got Hostname: {hostname}")
    domain = __grains__["domain"]
    fqdn = f"{hostname}.{domain}"
    log.debug(f"Got FQDN: {fqdn}")

    log.debug(f"Getting instance details for system {sid}")
    instances = __salt__["sap_control.get_system_instance_list"](
        instance_number=instances[0][hostname],
        fqdn=fqdn,
        username=username,
        password=password,
        verify=verify,
    )
    if not instances:
        msg = f"No instances found for {sid} on {fqdn}"
        log.error(f"{msg}")
        raise Exception(msg)
    log.debug(f"Got instance details\n{instances}")

    log.debug("Loop instances")
    for instance in instances:
        log.debug(f"Current instance\n{instance}")
        log.debug("Setting FQDN")
        instance["fqdn"] = f"{instance['hostname']}.{domain}"

        log.debug("Retrieving all parameters for processing")
        success, parameters_str = __salt__["sap_control.parameter_value"](
            instance_number=instance["instance"],
            parameter="",  # will return all parameters
            fqdn=instance["fqdn"],
            username=username,
            password=password,
            verify=verify,
        )
        if not success:
            log.warning("Could not retrieve parameters")
        else:
            parameters = {}
            for line in parameters_str.split("\n"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    parameters[key.strip()] = value.strip()
                elif line:
                    log.warning(f"Cannot determine key/value of parameter '{line}'")

        log.debug("Determine instance type")
        if "ABAP" in instance["features"]:
            log.debug("Processing ABAP instance")
            instance["type"] = "ABAP"
            log.debug("Retrieving DB host")
            if "SAPDBHOST" not in parameters:
                log.warning("Parameter SAPDBHOST does not exist")
            else:
                log.debug(f"Got DB host: {parameters['SAPDBHOST']}")
                system_data["db_host"] = parameters["SAPDBHOST"]

            log.debug("Retrieving DB name")
            # this is either the instance name OR the tenant name (for HDB)
            if "rsdb/dbid" not in parameters:
                log.warning("Parameter rsdb/dbid does not exist")
            else:
                log.debug(f"Got DB name: {parameters['rsdb/dbid']}")
                system_data["db_instance"] = parameters["rsdb/dbid"]

            log.debug("Retrieving ABAP component list")
            success, comps = __salt__["sap_control.get_abap_component_list"](
                instance_number=instance["instance"],
                fqdn=instance["fqdn"],
                username=username,
                password=password,
                verify=verify,
            )
            if not success:
                log.warning("Could not retrieve ABAP component list")
            elif not comps:
                log.warning("ABAP components does not exist")
            else:
                log.debug(f"Got ABAP components\n{comps}")
                system_data["software_components"] = comps

            log.debug("Retrieve ICM ports for instance")
            for icm_k, icm_v in parameters.items():
                if icm_k.startswith("icm/server_port_"):
                    log.debug(f"Got data for {icm_k}: {icm_v}")
                    params = icm_v.split(",")
                    protocol = None
                    port = None
                    for param in params:
                        log.debug(f"Processing '{param}'")
                        k_v = param.split("=")
                        key = k_v[0].strip()
                        value = k_v[1].strip()
                        if key == "PROT":
                            protocol = value
                        elif key == "PORT":
                            port = value
                        else:
                            log.warning(f"Unknown parameter {key}={value} for {icm_k}")
                    port = int(port)
                    if not protocol or not port:
                        log.warning(f"Protocol or port not defined for {icm_k}")
                        continue
                    if protocol.upper() == "HTTPS":
                        instance["httpsport"] = port
                        log.debug(f"Got ICM HTTPS port: {port}")
                    elif protocol.upper() == "HTTP":
                        instance["httpport"] = port
                        log.debug(f"Got ICM HTTP port: {port}")
                    else:
                        log.error(f"Unknown protocol '{protocol.upper()}', skipping")
                        continue
        elif "WEBDISP" in instance["features"]:
            log.debug("Processing WEBDISP instance")
            instance["type"] = "WEBDISP"
        elif "J2EE" in instance["features"]:
            log.debug("Processing J2EE instance")
            instance["type"] = "JAVA"
        elif "TREX" in instance["features"]:
            log.debug("Processing TREX instance")
            instance["type"] = "TREX"
        elif "HDB" in instance["features"]:
            log.debug("Processing HDB instance")
            instance["type"] = "HDB"
        elif "MESSAGESERVER" in instance["features"]:
            log.debug("Processing MESSAGESERVER instance")
            instance["type"] = "ASCS"
            # start of ports
            log.debug("Retrieving Ports")
            if "message_servers" not in system_data:
                system_data["message_servers"] = []
            message_server = {
                "host": instance["fqdn"],
            }

            log.debug("Adding messageserver port")
            etc_services = __salt__["file.grep"]("/etc/services", f"sapms{sid}")
            if not etc_services["retcode"]:
                log.debug("Message server port definiton found in /etc/services")
                # stdout = 'sapmsT20\t3620/tcp\t# SAP System Message Server Port'
                message_server["msport"] = etc_services["stdout"].split("\t")[1].split("/")[0]
                log.debug(f"Got messageserver port: {message_server['msport']}")
            else:
                message_server["msport"] = f"36{instance['instance']:02d}"
                log.debug(
                    f"Could not find message server port in /etc/services, using default {message_server['msport']}"
                )

            for icm_k, icm_v in parameters.items():
                if icm_k.startswith("ms/server_port_"):
                    log.debug(f"Got data for {icm_k}: {icm_v}")
                    params = icm_v.split(",")
                    protocol = None
                    port = None
                    for param in params:
                        log.debug(f"Processing '{param}'")
                        k_v = param.split("=")
                        key = k_v[0].strip()
                        value = k_v[1].strip()
                        if key == "PROT":
                            protocol = value
                        elif key == "PORT":
                            port = value
                        else:
                            log.warning(f"Unknown parameter {key}={value} for {icm_k}")
                    port = int(port)
                    if not protocol or not port:
                        log.warning(f"Protocol or port not defined for {icm_k}")
                        continue
                    if protocol.upper() == "HTTPS":
                        instance["httpsport"] = port
                        log.debug(f"Got MS HTTPS port: {port}")
                    elif protocol.upper() == "HTTP":
                        instance["httpport"] = port
                        log.debug(f"Got MS HTTP port: {port}")
                    else:
                        log.error(f"Unknown protocol '{protocol.upper()}', skipping")
                        continue
            if "httpport" not in message_server:
                message_server["httpport"] = f"81{instance['instance']:02d}"
                msg = (
                    f"Could not determine HTTP / HTTPS port of message server, "
                    f"setting to default {message_server['httpport']}"
                )
                log.warning(msg)
            system_data["message_servers"].append(message_server)
            # end of ports
            # start of Logon Groups
            log.debug("Retrieving Logon Groups")
            response = None
            for message_server in system_data["message_servers"]:
                session = requests.Session()
                if verify and "httpsport" in message_server:
                    session.verify = salt.utils.http.get_ca_bundle()
                    url = f"https://{message_server['host']}:{message_server['httpsport']}/msgserver/text/lglist"
                else:
                    session.verify = False
                    url = f"http://{message_server['host']}:{message_server['httpsport']}/msgserver/text/lglist"
                try:
                    res = requests.get(url, verify=verify)
                except RequestException:
                    log.debug(
                        f"Cannot reach message server {message_server['host']} to retrieve logon groups"
                    )
                    continue
                if not res.ok:
                    continue
                else:
                    response = res.text
                    break
            system_data["logon_groups"] = []
            if not response:
                log.warning(
                    "Could not reach any message server to retrieve logon groups, adding default logon group SPACE"
                )
                system_data["logon_groups"] = ["SPACE"]
            else:
                for logon_group in response.split("\n")[1:]:
                    # watch out for empty lines!
                    if logon_group:
                        system_data["logon_groups"].append(logon_group.split("\t")[0])
            log.debug(f"Got logon groups: {system_data['logon_groups']}")
            # end of Logon Groups
        else:
            instance["type"] = "UNKNOWN"

        log.debug("Retrieve instance properties")
        instance_properties = __salt__["sap_control.get_instance_properties"](
            instance_number=instance["instance"],
            fqdn=fqdn,
            username=username,
            password=password,
            verify=verify,
        )
        instance["name"] = instance_properties.get("INSTANCE_NAME", "UNKOWN_INSTANCE_NAME")
        instance_name = instance["instance"]
        del instance["instance"]
        system_data["instances"][instance_name] = instance
        log.debug(
            f"Added instance {instance_name} with details \n{system_data['instances'][instance_name]}"
        )

    log.trace(f"system_data\n{system_data}:")
    return system_data
