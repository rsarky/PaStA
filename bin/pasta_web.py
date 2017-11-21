#!/usr/bin/env python3

"""
PaStA - Patch Stack Analysis

Copyright (c) OTH Regensburg, 2017

Author:
  Ralf Ramsauer <ralf.ramsauer@oth-regensburg.de>

This work is licensed under the terms of the GNU GPL, version 2.  See
the COPYING file in the top-level directory.
"""

import os
import sys

from logging import getLogger

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from PaStA import *

from PaStA.Repository import PatchMail

from flask import Flask, render_template, request, Response
from flask_bootstrap import Bootstrap

from flask_nav import Nav
from flask_nav.elements import Navbar, View

from flask_wtf import FlaskForm

from wtforms import StringField
from wtforms.validators import InputRequired, Length

log = getLogger(__name__[-15:])

app = Flask(__name__, template_folder=os.path.join(os.getcwd(), 'templates'))
app.config['SECRET_KEY'] = 'foobar'
Bootstrap(app)

nav = Nav()

config = None
patch_groups_mbox = None


class CommitForm(FlaskForm):
    commit_hash = StringField('Commit Hash or Message-ID',
                              validators=[InputRequired(),
                                          Length(min=12, max=120)])

    def __init__(self, *args, **kwargs):
        FlaskForm.__init__(self, *args, **kwargs)

    def validate(self):
        if not FlaskForm.validate(self):
            return False

        if self.commit_hash.data not in config.repo:
            self.commit_hash.errors.append('Commit hash or message not found')
            return False

        return True


class MessageIDForm(FlaskForm):
    message_id = StringField('Message ID', validators=[InputRequired()])

    def __init__(self, *args, **kwargs):
        FlaskForm.__init__(self, *args, **kwargs)


@nav.navigation()
def mynavbar():
    return Navbar('PaStA shiny webfrontend',
                  View('Home', 'home'),
                  View('Mbox', 'mbox'))


@app.route("/")
def home():
    return render_template('index.html', title='Home')


@app.route("/view", methods=['GET'])
def view():
    id = request.args.get('id')
    if id not in config.repo:
        return 'Not found'

    commit = config.repo[id]

    if isinstance(commit, PatchMail):
        filename = config.repo.mbox[id]
        with open(filename, 'rb') as f:
            return Response(f.read(), mimetype='text/plain')

    fmt = '\n'.join(commit.format_message() + commit.diff.raw)

    return Response(fmt, mimetype='text/plain')


@app.route('/mbox_forward', methods=['GET'])
def mbox_forward():
    return ''


@app.route('/mbox_reverse', methods=['GET'])
def mbox_reverse():
    return ''


@app.route('/mbox', methods=['GET', 'POST'])
def mbox():
    lookup_form = CommitForm()
    repo = config.repo

    def render_mbox(base=None, history=None):
        return render_template('mbox.html',
                               title='Mbox',
                               lookup_form=lookup_form,
                               project=config.project_name,
                               base=base,
                               history=history)

    if not lookup_form.validate_on_submit():
        return render_mbox()

    commit = repo[lookup_form.commit_hash.data]
    id = commit.commit_hash

    if id not in patch_groups_mbox:
        return render_mbox(commit)

    elements = patch_groups_mbox.get_tagged(id) | patch_groups_mbox.get_untagged(id)

    # convert ids to commit objects
    elements = {repo.get_commit(x) for x in elements}
    # sort them by author_date
    elements = sorted(elements,
                      key=lambda x: x.author_date if isinstance(x, PatchMail)
                                    else x.commit_date,
                      reverse=True)

    history = []
    for element in elements:
        element_id = element.commit_hash
        if isinstance(element, PatchMail):
            message = element.mail_subject
            date = element.author_date
            found = sorted(config.repo.mbox.get_lists(element_id))
        else:
            message = '%s ("%s")' % (element_id[0:12], element.subject)
            date = element.commit_date
            found = ['Repository']
        date = date.strftime('%Y-%m-%d')
        history.append((element_id, date, message, found, element_id == id))

    return render_mbox(commit, history)


def web(c, prog, argv):
    global config
    global patch_groups_mbox
    config = c

    _, patch_groups_mbox = config.load_patch_groups(is_mbox=True,
                                                    must_exist=True)

    nav.init_app(app)
    app.run(debug=True)


if __name__ == '__main__':
    config = Config(sys.argv[1])
    web(config, sys.argv[0], sys.argv[2:])