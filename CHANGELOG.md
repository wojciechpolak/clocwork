# Changelog

All notable changes to clocwork will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) for public releases.

## [Unreleased]

First public release. clocwork reads a list of projects from `projects.toml`,
runs cloc once per project, and turns the counts into one report by language, by
project, and in total.

A project's `repo` is either a directory on this machine or a URL. Given a URL,
clocwork clones it with `--depth 1 --single-branch` and counts the clone, so the
tool runs where nothing is checked out, a CI job for instance. Clones live under
`$XDG_CACHE_HOME/clocwork`. `[defaults] cache` and `--cache` move them. Later
runs fetch rather than clone again, and `--no-fetch` skips the network to count
what is already there.

Licensed GPL-3.0-or-later, with an additional permission under section 7 that
puts the generated reports outside the licence, so a card can be embedded
under any terms.
