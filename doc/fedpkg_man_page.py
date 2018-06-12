# Print a man page from the help texts.


import os
import sys
import datetime

from six.moves.configparser import ConfigParser


if __name__ == '__main__':
    module_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    sys.path.insert(0, module_path)

    config = ConfigParser()
    config.read(
        os.path.join(module_path, 'conf', 'etc', 'rpkg', 'fedpkg.conf'))

    import pyrpkg.man_gen
    try:
        import fedpkg
    except ImportError:
        sys.path.append('src/')
        import fedpkg
    client = fedpkg.cli.fedpkgClient(config=config, name='fedpkg')
    pyrpkg.man_gen.generate(client.parser,
                            client.subparsers,
                            identity='fedpkg',
                            sourceurl='https://pagure.io/fedpkg/')
