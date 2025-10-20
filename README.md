# PySide6-substitutions

A crude script to assist with converting PySide2 enum accesses to PySide6.

PySide6 started using Python standard library enums to represent Qt enums.
With this change, many enum members are no longer accessible on the parent
Qt class and are instead only accessible through the enum class
(eg. `QtCore.QEvent.FocusOut` was removed in favour of `QtCore.QEvent.Type.FocusOut`).

This script will do basic substitutions to change from the old enum style
to the new way.

## Getting Started

The following steps will walk through how to perform the substitutions.


### Installation

No installation is required. Simply clone this repo:

.. code-block:: bash

    git clone https://github.com/AWhetter/PySide6-subsitutions.git


## Usage

⚠️ Substitutions are performed in place!⚠️

Run the `substitute.sh` file with a directory name
to perform the substitutions on all `.py` files in that directory.

.. code-block:: bash

    ./substitution.sh /path/to/python/src

Next, you'll need to validate the results of the script manually.
Many enum members share the same name between enums.
For example, an enum member `No` could refer to `QtWidgets.QDialogButtonBox.StandardButton.No`, `QtWidgets.QMessageBox.StandardButton.No`.
PySide6-substitutions will make a guess which one you mean,
but it may be incorrect.

A complete list of member name clashes is given in `conflicts.md <conflicts.md>`_.


## Contributing

### Running the tests

There are no tests currently.


### Code Style

No code style is enforced currently.


### Release Notes

* v1.0.0: Initial release.


## Versioning

We use `SemVer <https://semver.org/>`_ for versioning.
For the versions available, see the `tags on this repository <https://github.com/AWhetter/PySide6-subsitutions/tags>`_.


## License

This project is licensed under the MIT License.
See the `LICENSE.md <LICENSE.md>`_ file for details.
