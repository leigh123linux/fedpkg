# sitelib for noarch packages, sitearch for others (remove the unneeded one)
%{!?python_sitelib: %global python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")}

Name:           fedpkg
Version:        1.10
Release:        1%{?dist}
Summary:        Fedora utility for working with dist-git

Group:          Applications/System
License:        GPLv2+
URL:            http://fedorahosted.org/fedpkg
Source0:        http://fedorahosted.org/releases/f/e/fedpkg/fedpkg-%{version}.tar.bz2
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

Requires:       pyrpkg >= 1.13, redhat-rpm-config
Requires:       python-pycurl, koji, python-fedora
Requires:       fedora-cert, python-offtrac, bodhi-client
%if 0%{?rhel} == 5 || 0%{?rhel} == 4
Requires:       python-kitchen
%endif

BuildArch:      noarch
BuildRequires:  python-devel, python-setuptools, python-offtrac
# We br these things for man page generation due to imports
BuildRequires:  pyrpkg, fedora-cert
# This until fedora-cert gets fixed
BuildRequires:  python-fedora


%description
Provides the fedpkg command for working with dist-git


%prep
%setup -q


%build
%{__python} setup.py build
%{__python} src/fedpkg_man_page.py > fedpkg.1


%install
#rm -rf $RPM_BUILD_ROOT
%{__python} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT
%{__install} -d $RPM_BUILD_ROOT%{_mandir}/man1
%{__install} -p -m 0644 fedpkg.1 $RPM_BUILD_ROOT%{_mandir}/man1
rename es.py es $RPM_BUILD_ROOT%{_libexecdir}/fedpkg-fixbranches.py


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc COPYING README
%config(noreplace) %{_sysconfdir}/rpkg
%{_sysconfdir}/bash_completion.d
%{_bindir}/%{name}
%{_mandir}/*/*
%{_libexecdir}/fedpkg-fixbranches
# For noarch packages: sitelib
%{python_sitelib}/*


%changelog
* Tue Oct 09 2012 Jesse Keating <jkeating@redhat.com> - 1.10-1
- Force invalid dist values to 0 (spot) (jkeating)
- Fix a traceback in fixbranches (#817478) (jkeating)

* Mon Mar 12 2012 Jesse Keating <jkeating@redhat.com> - 1.9-1
- Wrap the prune command in a try (rhbz#785820) (jkeating)
- Use koji if we have it to get master details (rhbz#785234) (jkeating)
- Always send builds from master to 'rawhide' (rhbz#785234) (jkeating)
- Handle fedpkg calls not from a git repo (rhbz#785776) (jkeating)

* Thu Mar 01 2012 Jesse Keating <jkeating@redhat.com> - 1.8-1
- More completion fixes (jkeating)
- Add mock-config and mockbuild completion (jkeating)
- Simplify test for fedpkg availability. (ville.skytta)
- Fix ~/... path completion. (ville.skytta)
- Add --raw to bash completion (jkeating)
- Make things quiet when possible (jkeating)
- Fix property variables (jkeating)

* Sat Jan 14 2012 Jesse Keating <jkeating@redhat.com> - 1.7-1
- Adapt property overloading to new-style class. (bochecha)
- Use super(), now that rpkg uses new-style classes everywhere (bochecha)
- Add gitbuildurl to the bash completion. (jkeating)
- Handle koji config with unknown module name (jkeating)

* Mon Nov 21 2011 Jesse Keating <jkeating@redhat.com> - 1.6-1
- Replace -c with -C for the --config option (jkeating)
- Package up fedpkg-fixbranches (#751507) (jkeating)
- Use old style of super class calls (jkeating)

* Mon Nov 07 2011 Jesse Keating <jkeating@redhat.com> - 1.5-1
- Pass along the return value from import_srpm (jkeating)
- Whitespace cleanup (jkeating)

* Mon Nov 07 2011 Jesse Keating <jkeating@redhat.com> - 1.4-1
- Use the GPLv2 content for COPYING to match intent. (jkeating)

* Thu Nov 03 2011 Jesse Keating <jkeating@redhat.com> - 1.3-1
- Fix buildrequires (jkeating)
- Don't register a nonexestant target (jkeating)
- Drop koji-rhel.conf file (jkeating)
- Fix up the setup.py (jkeating)

* Thu Nov 03 2011 Jesse Keating <jkeating@redhat.com> - 1.2-1
- Catch raises in the libraries (jkeating)
- Fix the fixbranches script for new module name (jkeating)
- srpm takes arguments, pass them along (jkeating)
- Get error output from user detection failures (jkeating)
- Get the user name from the Fedora SSL certificate. (bochecha)
- Fix crash when detecting Rawhide. (bochecha)

* Fri Oct 28 2011 Jesse Keating <jkeating@redhat.com> - 1.1-1
- Overload curl stuff (jkeating)
- Hardcode fedpkg version requires (jkeating)
- Fix up changelog date (jkeating)
