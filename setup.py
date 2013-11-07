import os, sys, subprocess, numpy, shutil
from distutils.core  import setup, Extension
try:
    from Cython.Distutils import build_ext
    has_cython = True
except ImportError:
    has_cython = False

if sys.version_info[0] < 3:
    import ConfigParser as configparser
else:
    import configparser

def check_hdf5version(hdf5_includedir):
    try:
        f = open(os.path.join(hdf5_includedir,'H5pubconf-64.h'))
    except IOError:
        try:
            f = open(os.path.join(hdf5_includedir,'H5pubconf-32.h'))
        except IOError:
            try:
                f = open(os.path.join(hdf5_includedir,'H5pubconf.h'))
            except IOError:
                return None
    hdf5_version = None
    for line in f:
        if line.startswith('#define H5_VERSION'):
            hdf5_version = line.split()[2]
    return hdf5_version

def check_ifnetcdf4(netcdf4_includedir):
    try:
        f = open(os.path.join(netcdf4_includedir,'netcdf.h'))
    except IOError:
        return False
    isnetcdf4 = False
    for line in f:
        if line.startswith('nc_inq_compound'):
            isnetcdf4 = True
    return isnetcdf4

def check_api(inc_dirs):
    has_rename_grp = False
    has_nc_inq_path = False
    for d in inc_dirs:
        try:
            f = open(os.path.join(d,'netcdf.h'))
        except IOError:
            continue
        for line in f:
            if line.startswith('nc_rename_grp'):
                has_rename_grp = True
            if line.startswith('nc_inq_path'):
                has_nc_inq_path = True
        break
    return has_rename_grp, has_nc_inq_path

def getnetcdfvers(libdirs):
    """
    Get the version string for the first netcdf lib found in libdirs.
    (major.minor.release). If nothing found, return None.
    """

    import os, re, sys, ctypes

    if sys.platform.startswith('win'):
        regexp = re.compile('^netcdf.dll$')
    elif sys.platform.startswith('cygwin'):
        bindirs = []
        for d in libdirs:
            bindirs.append(os.path.dirname(d)+'/bin')
        regexp = re.compile(r'^cygnetcdf-\d.dll')
    elif sys.platform.startswith('darwin'):
        regexp = re.compile(r'^libnetcdf.dylib')
    else:
        regexp = re.compile(r'^libnetcdf.so')


    if sys.platform.startswith('cygwin'):
        dirs = bindirs
    else:
        dirs = libdirs
    for d in dirs:
        try:
            candidates = [x for x in os.listdir(d) if regexp.match(x)]
            if len(candidates) != 0:
                candidates.sort(key=lambda x: len(x))   # Prefer libfoo.so to libfoo.so.X.Y.Z
                path = os.path.abspath(os.path.join(d, candidates[0]))
            lib = ctypes.cdll.LoadLibrary(path)
            inq_libvers = lib.nc_inq_libvers
            inq_libvers.restype = ctypes.c_char_p
            vers = lib.nc_inq_libvers()
            return vers.split()[0]
        except Exception:
            pass   # We skip invalid entries, because that's what the C compiler does

    return None

HDF5_dir = os.environ.get('HDF5_DIR')
netCDF4_dir = os.environ.get('NETCDF4_DIR')
HDF5_includedir = os.environ.get('HDF5_INCDIR')
netCDF4_includedir = os.environ.get('NETCDF4_INCDIR')
HDF5_libdir = os.environ.get('HDF5_LIBDIR')
netCDF4_libdir = os.environ.get('NETCDF4_LIBDIR')
szip_dir = os.environ.get('SZIP_DIR')
szip_libdir = os.environ.get('SZIP_LIBDIR')
szip_incdir = os.environ.get('SZIP_INCDIR')
USE_NCCONFIG = os.environ.get('USE_NCCONFIG')

setup_cfg = 'setup.cfg'
# contents of setup.cfg will override env vars.
ncconfig = None
if os.path.exists(setup_cfg):
    sys.stdout.write('reading from setup.cfg...\n')
    config = configparser.SafeConfigParser()
    config.read(setup_cfg)
    try: HDF5_dir = config.get("directories", "HDF5_dir")
    except: pass
    try: HDF5_libdir = config.get("directories", "HDF5_libdir")
    except: pass
    try: HDF5_incdir = config.get("directories", "HDF5_incdir")
    except: pass
    try: netCDF4_dir = config.get("directories", "netCDF4_dir")
    except: pass
    try: netCDF4_libdir = config.get("directories", "netCDF4_libdir")
    except: pass
    try: netCDF4_incdir = config.get("directories", "netCDF4_incdir")
    except: pass
    try: szip_dir = config.get("directories", "szip_dir")
    except: pass
    try: szip_libdir = config.get("directories", "szip_libdir")
    except: pass
    try: szip_incdir = config.get("directories", "szip_incdir")
    except: pass
    try: USE_NCCONFIG = config.get("options", "use_ncconfig")
    except: pass
    try: ncconfig = config.get("options", "ncconfig")
    except: pass

# if USE_NCCONFIG set, and nc-config works, use it.
if USE_NCCONFIG is not None:
    # if NETCDF4_DIR env var is set, look for nc-config in NETCDF4_DIR/bin.
    if ncconfig is None:
        if netCDF4_dir is not None:
            ncconfig = os.path.join(netCDF4_dir,'bin/nc-config')
        else: # otherwise, just hope it's in the users PATH.
            ncconfig = 'nc-config'
    retcode =  subprocess.call([ncconfig,'--libs'],stdout=subprocess.PIPE)
else:
    retcode = 1

if not retcode:
    sys.stdout.write('using nc-config ...\n')
    dep=subprocess.Popen([ncconfig,'--libs'],stdout=subprocess.PIPE).communicate()[0]
    libs = [str(l[2:].decode()) for l in dep.split() if l[0:2].decode() == '-l' ]
    lib_dirs = [str(l[2:].decode()) for l in dep.split() if l[0:2].decode() == '-L' ]
    dep=subprocess.Popen([ncconfig,'--cflags'],stdout=subprocess.PIPE).communicate()[0]
    inc_dirs = [str(i[2:].decode()) for i in dep.split() if i[0:2].decode() == '-I']
# if nc-config didn't work (it won't on windows), fall back on brute force method
else:
    dirstosearch =  [os.path.expanduser('~'),'/usr/local','/sw','/opt','/opt/local', '/usr']

    if HDF5_includedir is None and HDF5_dir is None:
        sys.stdout.write("""
HDF5_DIR environment variable not set, checking some standard locations ..\n""")
        for direc in dirstosearch:
            sys.stdout.write('checking %s ...\n' % direc)
            hdf5_version = check_hdf5version(os.path.join(direc, 'include'))
            if hdf5_version is None or hdf5_version[1:6] < '1.8.0':
                continue
            else:
                HDF5_dir = direc
                HDF5_includedir = os.path.join(direc, 'include')
                sys.stdout.write('HDF5 found in %s\n' % HDF5_dir)
                break
        if HDF5_dir is None:
            raise ValueError('did not find HDF5 headers')
    else:
        if HDF5_includedir is None:
             HDF5_includedir = os.path.join(HDF5_dir, 'include')
        hdf5_version = check_hdf5version(HDF5_includedir)
        if hdf5_version is None:
            raise ValueError('did not find HDF5 headers in %s' % HDF5_includedir)
        elif hdf5_version[1:6] < '1.8.0':
            raise ValueError('HDF5 version >= 1.8.0 is required')

    if netCDF4_includedir is None and netCDF4_dir is None:
        sys.stdout.write( """
NETCDF4_DIR environment variable not set, checking standard locations.. \n""")
        for direc in dirstosearch:
            sys.stdout.write('checking %s ...\n' % direc)
            isnetcdf4 = check_ifnetcdf4(os.path.join(direc, 'include'))
            if not isnetcdf4:
                continue
            else:
                netCDF4_dir = direc
                netCDF4_includedir = os.path.join(direc, 'include')
                sys.stdout.write('netCDF4 found in %s\n' % netCDF4_dir)
                break
        if netCDF4_dir is None:
            raise ValueError('did not find netCDF version 4 headers')
    else:
        if netCDF4_includedir is None:
            netCDF4_includedir = os.path.join(netCDF4_dir, 'include')
        isnetcdf4 = check_ifnetcdf4(netCDF4_includedir)
        if not isnetcdf4:
            raise ValueError('did not find netCDF version 4 headers %s' % netCDF4_includedir)

    if HDF5_libdir is None and HDF5_dir is not None:
        HDF5_libdir = os.path.join(HDF5_dir, 'lib')

    if netCDF4_libdir is None and netCDF4_dir is not None:
        netCDF4_libdir = os.path.join(netCDF4_dir, 'lib')

    libs = ['netcdf','hdf5_hl','hdf5','z']
    lib_dirs = [netCDF4_libdir,HDF5_libdir]
    inc_dirs = [netCDF4_includedir,HDF5_includedir]

    # add szip to link if desired.
    if szip_libdir is None and szip_dir is not None:
        szip_libdir = os.path.join(szip_dir, 'lib')
    if szip_incdir is None and szip_dir is not None:
        szip_incdir = os.path.join(szip_dir, 'include')
    if szip_incdir is not None and szip_libdir is not None:
        libs.append('sz')
        lib_dirs.append(szip_libdir)
        inc_dirs.append(szip_incdir)

# append numpy include dir.
inc_dirs.append(numpy.get_include())

# get netcdf library version.
netcdf_lib_version = getnetcdfvers(lib_dirs)
if netcdf_lib_version is None:
    sys.stdout.write('unable to detect netcdf library version')
else:
    sys.stdout.write('using netcdf library version %s\n' % netcdf_lib_version)

if has_cython:
    sys.stdout.write('using Cython to compile netCDF4.pyx...\n')
    # recompile netCDF4.pyx
    extensions = [Extension("netCDF4",["netCDF4.pyx"],libraries=libs,library_dirs=lib_dirs,include_dirs=inc_dirs,runtime_library_dirs=lib_dirs)]
    # remove netCDF4.c file if it exists, so cython will recompile netCDF4.pyx.
    if len(sys.argv) >= 2 and sys.argv[1] == 'build' and os.path.exists('netCDF4.c'):
        os.remove('netCDF4.c')
    # this determines whether renameGroup and filepath methods will work.
    has_rename_grp, has_nc_inq_path = check_api(inc_dirs)
    f = open('constants.pyx','w')
    if has_rename_grp:
        sys.stdout.write('netcdf lib has group rename capability\n')
        f.write('DEF HAS_RENAME_GRP = 1\n')
    else:
        sys.stdout.write('netcdf lib does not have group rename capability\n')
        f.write('DEF HAS_RENAME_GRP = 0\n')
    if has_nc_inq_path:
        sys.stdout.write('netcdf lib has nc_inq_path function\n')
        f.write('DEF HAS_NC_INQ_PATH = 1\n')
    else:
        sys.stdout.write('netcdf lib does not have nc_inq_path function\n')
        f.write('DEF HAS_NC_INQ_PATH = 0\n')
    f.close()
    cmdclass = {'build_ext': build_ext}
else:
    # use existing netCDF4.c, don't need cython.
    extensions = [Extension("netCDF4",["netCDF4.c"],libraries=libs,library_dirs=lib_dirs,include_dirs=inc_dirs,runtime_library_dirs=lib_dirs)]
    cmdclass = {}

setup(name = "netCDF4",
  cmdclass = cmdclass,
  version = "1.0.7",
  long_description = "netCDF version 4 has many features not found in earlier versions of the library, such as hierarchical groups, zlib compression, multiple unlimited dimensions, and new data types.  It is implemented on top of HDF5.  This module implements most of the new features, and can read and write netCDF files compatible with older versions of the library.  The API is modelled after Scientific.IO.NetCDF, and should be familiar to users of that module.\n\nThis project has a `Subversion repository <http://code.google.com/p/netcdf4-python/source>`_ where you may access the most up-to-date source.",
  author            = "Jeff Whitaker",
  author_email      = "jeffrey.s.whitaker@noaa.gov",
  url               = "http://netcdf4-python.googlecode.com/svn/trunk/docs/netCDF4-module.html",
  download_url      = "http://code.google.com/p/netcdf4-python/downloads/list",
  scripts           = ['utils/nc3tonc4','utils/nc4tonc3'],
  platforms         = ["any"],
  license           = "OSI Approved",
  description = "Provides an object-oriented python interface to the netCDF version 4 library.",
  keywords = ['numpy','netcdf','data','science','network','oceanography','meteorology','climate'],
  classifiers = ["Development Status :: 3 - Alpha",
                 "Intended Audience :: Science/Research",
                 "License :: OSI Approved",
                 "Topic :: Software Development :: Libraries :: Python Modules",
                 "Topic :: System :: Archiving :: Compression",
                 "Operating System :: OS Independent"],
  py_modules = ["netcdftime","netCDF4_utils"],
  ext_modules = extensions)
