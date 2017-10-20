ChangeLog
=========

1.30 (2017-10-20)
-----------------

- Add missing files to dist tarball (cqi)
- Tests for update command (cqi)
- Add support for module commands (mprahl)
- Clean rest cert related code (cqi)
- Remove fedora cert (cqi)
- Override build URL for Koji (cqi)
- changing anongiturl to use src.fp.o instead of pkgs.fp.o. - #119 (tflink)
- Add tests (cqi)
- Enable lookaside_namespaced - #130 (cqi)
- Detect dist tag correctly for RHEL and CentOS - #141 (cqi)
- Remove deprecated call to platform.dist (cqi)
- Do not prompt hint for SSL cert if fail to log into Koji (cqi)
- Add more container-build options to bash completion (cqi)
- Remove osbs from bash completion - #138 (cqi)
- Install executables via entry_points - #134 (cqi)
- Fix container build target (lsedlar)
- Get correct build target for rawhide containers (lsedlar)
- Update error message to reflect deprecation of --dist option (pgier)

v1.29 (2017-08-11)
------------------

- Remove unused variable in Commands.retire (cqi)
- No more pkgdb. (rbean)
- Add --arches to build completions (ville.skytta)
- Add ppc64le to arch completions (ville.skytta)
- Explain how to write a note in multiple lines in update template - #123 (cqi)
- Remove code that handles secondary arch (cqi)
- Simplify passing arguments when creating Command object - #14 (cqi)
- Set koji profile for secondary arch immediately (cqi)
- Use profile to load Koji configuration - #97 (cqi)
- Remove push.default from clone_default - #109 (cqi)
- remove special handling of s390 specific packages (dan)
- Replace fedorahosted.org with pagure.io in manpage - #113 (cqi)
- Remove tracbaseurl from conf file - #112 (cqi)
- Set disttag properly (cqi)
- koji stage config moved, update fedpkg defaults (maxamillion)
- Specific help of --release for fedpkg - rhbz#1054440 (cqi)

v1.28 (2017-02-24)
------------------

- Restore anonymous clone link - rhbz#1425913 (cqi)

v1.27 (2017-02-22)
------------------

- Python 3.6 invalid escape sequence deprecation fixes (ville.skytta)
- Disable tag inheritance check - #98 (cqi)

v1.26 (2016-12-15)
------------------

- fedpkg clone -a uses https transport - BZ#1188634 (cqi)
- Fix handle unicode chars in git log - BZ#1404724 (cqi)
- Fix: make fedpkg workable with bodhi 2 CLI - #87 (cqi)
- Fix --dist/--release option for 'master' %dist detection (praiskup)
- sha512 should be also used in fedpkg-stage (cqi)
- conf: s/kerberos_realm/kerberos_realms/ (i.gnatenko.brain)
- Update config with new lookaside url (puiterwijk)
- Use system trust list for lookaside (puiterwijk)
- Specific help of --release for fedpkg - rhbz#1054440 (cqi)
- Bash completion for --mock-config (cqi)
- Remove unnecessary entry point (cqi)
- Add missing import to man page script (lsedlar)
- lookaside: We now use sha512 to upload the sources (bochecha)
- Move to the new sources file format (bochecha)
- Fix man page generator (lsedlar)
- Accept the realms argument in Commands class - #14 (lsedlar)
- Add kerberos realm to config files (lsedlar)
- Move release guide to doc directory (cqi)
- Add --with-changelog to shell completion (cqi)
- Avoid sys.exit - #52 (cqi)
- Add --release to bash completion (cqi)
- remove the ppc and arm packages as they are now built in regular koji
  (dennis)
- Do not send a certificate if none exists (puiterwijk)
- New source code layout (cqi)
- Set push.default to simple (cqi)
- Fix PEP8 errors (cqi)
- Integration between setuptools and nosetests (cqi)
- New fedpkg-stage for developers to use stage infra - #41 (cqi)
- enable target dest for rawhide to have trailing pieces (dennis)
- python3: improve Python 3.x compatibility (pavlix)
