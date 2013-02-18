'''
Qemu Command Wrapper
====================

The qemu system comes with powerful tools, such as qemu-img and qemu-nbd which
are used here to build up kvm images.
'''

# Import python libs
import os
import glob
import tempfile
import time
import yaml

# Import salt libs
import salt.utils

def __virtual__():
    '''
    Only load if qemu-img and qemu-nbd are installed
    '''
    if salt.utils.which('qemu-img') and salt.utils.which('qemu-nbd'):
        return 'qemu'
    return False


def make_image(location, size, fmt):
    '''
    Create a blank virtual machine image file of the specified size in
    megabytes. The image can be created in any format supported by qemu

    CLI Example::

        salt '*' qemu.make_image /tmp/image.qcow 2048 qcow2
        salt '*' qemu.make_image /tmp/image.raw 10240 raw
    '''
    if not os.path.isabs(location):
        return ''
    if not os.path.isdir(os.path.dirname(location)):
        return ''
    if not __salt__['cmd.retcode'](
            'qemu-img create -f {0} {1} {2}M'.format(
                fmt,
                location,
                size)):
        return location
    return ''


def nbd_connect(image):
    '''
    Activate nbd for an image file.

    CLI Example::
        
        salt '*' qemu.nbd_connect /tmp/image.raw
    '''
    if not os.path.isfile(image):
        return ''
    __salt__['cmd.run']('modprobe nbd max_part=63')
    for nbd in glob.glob('/dev/nbd?'):
        if __salt__['cmd.retcode']('fdisk -l {0}'.format(nbd)):
            __salt__['cmd.run'](
                    'qemu-nbd -c {0} {1}'.format(nbd, image)
                    )
            return nbd
    return ''


def nbd_mount(nbd):
    '''
    Pass in the nbd connection device location, mount all partitions and return
    a dict of mount points

    CLI Example::

        salt '*' qemu.nbd_mount /dev/nbd0
    '''
    ret = {}
    for part in glob.glob('{0}p*'.format(nbd)):
        root = os.path.join(
                tempfile.gettempdir(),
                'nbd',
                os.path.basename(nbd))
        m_pt = os.path.join(root, os.path.basename(part))
        time.sleep(1)
        mnt = __salt__['mount.mount'](m_pt, part, True)
        if not mnt is True:
            continue
        ret[m_pt] = part
    return ret


def nbd_init(image):
    '''
    Mount the named image via qemu-nbd and return the mounted roots

    CLI Example::

        salt '*' qemu.nbd_init /srv/image.qcow2
    '''
    nbd = nbd_connect(image)
    if not nbd:
        return ''
    return nbd_mount(nbd)


def nbd_clear(mnt):
    '''
    Pass in the mnt dict returned from nbd_mount to unmount and disconnect
    the image from nbd. If all of the partitions are unmounted return an
    empy dict, otherwise return a dict containing the still mounted
    partitions

    CLI Example::

        salt '*' qemu.nbd_clear '{/mnt/foo: /dev/nbd0p1}'
    '''
    if isinstance(mnt, str):
        mnt = yaml.load(mnt)
    ret = {}
    nbds = set()
    for m_pt, dev in mnt.items():
        mnt_ret = __salt__['mount.umount'](m_pt)
        if not mnt_ret is True:
            ret[m_pt] = dev
        nbds.add(dev[:dev.rindex('p')])
    if ret:
        return ret
    for nbd in nbds:
        __salt__['cmd.run']('qemu-nbd -d {0}'.format(nbd))
    return ret


def seed(location):
    '''
    Make sure that the image at the given location is mounted, salt is
    installed, keys are seeded, and execute a state run

    CLI Example::

        salt '*' qemu.seed /tmp/image.qcow2
    '''
    mnt = nbd_init(location)
    mpt = mnt.keys()[0]
    __salt__['mount.mount'](
            os.path.join(mpt, 'dev'),
            'udev',
            fstype='devtmpfs')
    # Generate the minion's key
    # Send the key to the master for approval
    # Execute chroot routine
    sh_ = '/bin/sh'
    dl_ = 'curl'
    if os.path.isfile(os.path.join(mpt, '/usr/bin/curl')):
        dl_ = '/usr/bin/curl -L http://bootstrap.saltstack.org > bootstrap.sh && sh bootstrap.sh'
    elif os.path.isfile(os.path.join(mpt, '/bin/curl')):
        dl_ = '/bin/curl -L http://bootstrap.saltstack.org > bootstrap.sh && sh bootstrap.sh'
    if os.path.isfile(os.path.join(mpt, 'bin/bash')):
        sh_ = '/bin/bash'

    cmd = 'chroot {0} {1} -c \'{2}\''.format(
            mpt,
            sh_,
            dl_)
    __salt__['cmd.run'](cmd)
    __salt__['mount.umount'](os.path.join(mpt, 'dev'))
    nbd_clear(mnt)


def bootstrap(location, size, fmt):
    '''
    HIGHLY EXPERIMENTAL
    Bootstrap a virtual machine image

    location:
        The location to create the image

    size:
        The size of the image to create in megabytes

    fmt:
        The image format, raw or qcow2

    CLI Example::
        @todo
    '''
    location = make_image(location, size, fmt)
    if not location:
        return ''
    nbd = nbd_connect(location)
    __salt__['partition.mklabel'](nbd, 'msdos')
    __salt__['partition.mkpart'](nbd, 'primary', 'ext4', 1, -1)
    __salt__['partition.probe'](nbd)
    __salt__['partition.mkfs']('{0}p1'.format(nbd), 'ext4')
    mnt = nbd_mount(nbd)
    #return __salt__['pkg.bootstrap'](nbd, mnt.keys()[0])
