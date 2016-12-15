ChangeLog
=========

NEXT
----

- fedpkg clone -a uses https transport - BZ#1188634 (cqi)
- Fix handle unicode chars in git log - BZ#1404724 (cqi)
- Fix: make fedpkg workable with bodhi 2 CLI - #87 (cqi)
- Fix --dist/--release option for 'master' %dist detection (praiskup)

v1.26-3 (2016-12-12)
--------------------

- sha512 should be also used in fedpkg-stage (cqi)
- conf: s/kerberos_realm/kerberos_realms/ (i.gnatenko.brain)

v1.26-2 (2016-12-09)
--------------------

- Update config with new lookaside url (puiterwijk)
- Use system trust list for lookaside (puiterwijk)

v1.26-1 (2016-12-02)
--------------------

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
