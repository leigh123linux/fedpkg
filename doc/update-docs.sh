#!/bin/bash

# Copyright (C) 2019 Red Hat, Inc.
# SPDX-License-Identifier:      GPL-2.0

trap cleanup EXIT

prod=fedpkg  # product name
prod_git=https://pagure.io/fedpkg.git
prod_doc_git=ssh://git@pagure.io/docs/fedpkg.git

function cleanup() {
    printf "Run cleanup\\n"
    rm -rf  "$dir_prod" "$dir_prod_doc"
}

if [ -z "$1" ]; then
    printf "Usage:\\n"
    printf "\\t%s release_version\\n" "$0"
    exit 1
fi

set -e
dir_prod=$(mktemp -d /tmp/${prod}.XXX) || { echo "Failed to create temp directory"; exit 1; }
git clone "$prod_git" "$dir_prod"
pushd "$dir_prod"/doc
make html
popd

dir_prod_doc=$(mktemp -d /tmp/prod-doc.XXX) || { echo "Failed to create temp directory"; exit 1; }
git clone "$prod_doc_git" "$dir_prod_doc"
pushd "$dir_prod_doc"
git rm -fr ./*
cp -r "$dir_prod"/doc/build/html/* ./
git add .
git commit -s -m "Publish documentation for release $1"
git push origin master
popd
