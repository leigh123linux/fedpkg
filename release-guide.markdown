# Releasing new version of rpkg/fedpkg to Fedora

So you want to build new packages? Here is how:

## Make an upstream release

All this should happen in git checkout of the project from Pagure.

First, bump the version in `setup.py` (using a text editor). Commit the change.
Create a git tag and push it to the server.

    $ git tag -a $VERSION
    $ git push origin --tags

Generate a changelog from git log. Save the output for later.

    $ ./git-changelog -f $PREVIOUS_VERSION

The `$PREVIOUS_VERSION` should be name of tag marking last release.

Next, create a tarball with the code:

    $ python setup.py sdist

Upload the tarball from `dist/` subdirectory to Pagure releases. Make sure you
are uploading `.tar.bz2` file (use `--formats=bztar` for `sdist` if necessary).

## Update Fedora package

This happens in checkout of dist-git repository (most likely created by `fedpkg
clone`). Switch to `master` branch. Builds from `master` will go into Fedora
Rawhide. Generally we try to keep a single version of the specfile for all
supported releases.

First, import new sources tarball. Make sure to use the same tarball that you
uploaded to Pagure before.

    $ fedpkg new-sources ../path/to/tarball.tar.bz2

Then update the spec file.

    $ rpmdev-bumpspec -n $VERSION rpkg.spec

Open the spec file in a text editor and add the changelog generated before to
the `%changelog` section.

Commit your changes to dist-git. Make sure you include the `sources` file.

Test the package by creating a scratch build.

    $ fedpkg scratch-build --srpm

If that succeeded, push your changes to dist-git.

    $ git push origin master

Test the package by doing a scratch build from SCM. This will do the same work
a regular build would do, but will not publish the package.

    $ fedpkg scratch-build

Repeat the steps above for all active branches (currently `f24`, `f23`, `f22`,
`el6` and `epel7`). Instead of making a new commit simply merge `master`
branch. Try to use fast forward to keep the history nice.

    $ git merge master

If all the scratch builds succeeded, you can do the real builds. This again
needs to happen on all branches.

    $ fedpkg build

For Rawhide, the package will be available in the next compose automatically.
For other versions you need to create an update in [Bodhi]. It is a good idea
to put both *rpkg* and *fedpkg* into the same update.

[Bodhi]: https://bodhi.fedoraproject.org/
