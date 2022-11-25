# SaltStack general SAP extension
This SaltStack extension handles generic SAP operations.

**THIS PROJECT IS NOT ASSOCIATED WITH SAP IN ANY WAY**

## Installation
Run the following to install the SaltStack general SAP extension:
```bash
salt-call pip.install saltext.sap
```
Keep in mind that this package must be installed on every minion that should utilize the states and execution modules.

Alternatively, you can add this repository directly over gitfs
```yaml
gitfs_remotes:
  - https://github.com/SAPUCC/saltext-sap.git:
    - root: src/saltext/sap
```
In order to enable this, logical links under `src/saltext/sap/` from `_<dir_type>` (where the code lives) to `<dir_type>` have been placed, e.g. `_modules` -> `modules`. This will double the source data during build, but:
 * `_modules` is required for integrating the repo over gitfs
 * `modules` is required for the salt loader to find the modules / states

## Usage
A state using the generic SAP extension looks like this:
```jinja
{%- set system_data = salt["sap.get_system_data"](sid="S4H", username="sapadm", password="Abcd1234!") %}
{%- set message_server = system_data["message_servers"][0] %}
{%- set logon_group = system_data["logon_groups"][0] %}

SLD config is present on S4H:
  sap_nwabap.sld_config_present:
    - name: SLD_DS_TARGET
    - sid: S4H
    - client: "000"
    - message_server_host: {{ message_server["host"] }}
    - message_server_port: {{ message_server["msport"] }}
    - logon_group: {{ logon_group }}
    - username: SALT
    - password: __slot__:salt:vault.read_secret(path="nwabap/S4H/000", key="SALT")
```

## Docs
See https://saltext-sap.readthedocs.io/ for the documentation.

## Contributing
We would love to see your contribution to this project. Please refer to `CONTRIBUTING.md` for further details.

## License
This project is licensed under GPLv3. See `LICENSE.md` for the license text and `COPYRIGHT.md` for the general copyright notice.
