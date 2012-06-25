#
# ========================================================
# Copyright (c) 2012 Whamcloud, Inc.  All rights reserved.
# ========================================================


import subprocess
import os
import sys
from chroma_agent.agent_daemon import daemon_log


def run(arg_list, shell = False):
    """Run a subprocess, and return a tuple of rc, stdout, stderr.

    Note: we buffer all output, so do not run commands with large outputs
    using this function.
    """

    daemon_log.debug("shell.run: %s" % arg_list)
    os.environ["TERM"] = ""

    p = subprocess.Popen(arg_list, shell = shell,
                         stdout = subprocess.PIPE,
                         stderr = subprocess.PIPE,
                         close_fds = True)
    rc = p.wait()
    stdout_buf, stderr_buf = p.communicate()
    sys.stderr.write(stderr_buf)
    sys.stderr.write(stdout_buf)

    return rc, stdout_buf, stderr_buf


def try_run(arg_list, shell = False):
    """Run a subprocess, and raise an exception if it returns nonzero.  Return
    stdout string."""
    rc, stdout, stderr = run(arg_list, shell)
    if rc != 0:
        raise RuntimeError("Error (%s) running '%s': '%s' '%s'" % (rc, " ".join(arg_list), stdout, stderr))

    return stdout
