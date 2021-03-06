# -*- coding: utf-8 -*-

import sys
import commands
import os

clone_url_default = "https://gforge.inria.fr/git/metalibm/metalibm-lugdunum.git"
default_install_script = "/tmp/metalibm-lugdunum/INSTALL"

def extract_option(opt_name, default_value):
  if opt_name in sys.argv:
    return sys.argv[sys.argv.index(opt_name)+1]
  else:
    return default_value


install_dir    = extract_option("--install-dir", "/tmp")
install_script = extract_option("--install-script", default_install_script)
clone_url      = extract_option("--clone-url", clone_url_default)
gforge_login   = extract_option("--gforge-login", "")
branch         = extract_option("--branch", "master")

enable_step_opt = extract_option("--enable-steps", "")
if enable_step_opt == "":
  enable_steps = [0, 1, 2, 3, 4]
else:
  enable_steps = [int(s) for s in enable_step_opt.split(",")]

root_dir = os.path.join(install_dir, "metalibm-lugdunum")


def execute_cmd(title, cmd):
  print title
  status, output = commands.getstatusoutput(cmd)
  if status:
    print output
    print cmd
    print title, " FAILED"
    sys.exit(1)
  else:
    print "   SUCCESS"

move_step_cmd = ("cp -f %s %s" % (install_script, root_dir)) if install_script != default_install_script else "echo \"   nothing to do\""

step_list = [ 
  ("cleaning install dir", "rm -rf %s/metalibm-lugdunum/" % install_dir),

  ("cloning metalibm-lugdunum", "cd %s && git clone %s" % (install_dir, clone_url)),

  ("moving INSTALL script", move_step_cmd),

  ("launching INSTALL", "cd %s && BRANCH=%s LOGIN=%s sh INSTALL" % (root_dir, branch, gforge_login)),

  ("testing metalibm install", "bash -c \"cd %s && source %s/metalibm_setup_env.bash; python %s/valid/non_regression.py\"" % (install_dir, root_dir, root_dir)),
]

if "--help" in sys.argv:
  for i in xrange(len(step_list)):
    print i, ":", step_list[i][0]
else:
  for index in enable_steps:
    execute_cmd(step_list[index][0], step_list[index][1])
