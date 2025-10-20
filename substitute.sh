#!/bin/bash
find $1 -type f -name '*.py' | xargs sed --regexp-extended --file=$(dirname $0)/pyside6.sed -i
