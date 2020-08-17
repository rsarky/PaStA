#! /bin/bash
set -e

cd "$(dirname "$0")"
./pasta sync -clear all
./pasta sync -mbox
./pasta analyse rep
./pasta rate
./pasta form_patchwork_relations
