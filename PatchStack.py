import csv
from distutils.version import LooseVersion
import functools
from multiprocessing import Pool, cpu_count
import re


class StringVersion:
    """
    Parse a version string like "rt34"
    """

    regex = re.compile('([a-zA-Z]+)([0-9]+)')

    def __init__(self, version_string=''):
        self.string = ''
        self.version = -1

        if not version_string:
            return

        if not self.regex.match(version_string):
            raise Exception('VersionString does not mach: ' + version_string)

        res = self.regex.search(version_string)
        self.string = res.group(1)
        self.version = int(res.group(2))

    def __lt__(self, other):
        # if self.string is empty, then we are newer than the other one
        if not self.string and not not other.string:
            return False
        elif not other.string and not not self.string:
            return True

        # if both version strings are defined, then they must equal
        if self.string != other.string:
            raise Exception('Unable to compare ' + str(self) + ' with ' + str(other))

        return self.version < other.version

    def __str__(self):
        if len(self.string) or self.version != -1:
            return '-' + self.string + str(self.version)
        return ''


class KernelVersion:
    """ Kernel Version

    This class represents a kernel version with a version nomenclature like

    3.12.14.15-rc4-extraversion3

    and is able to compare versions of the class
    """

    versionDelimiter = re.compile('\.|\-')

    def __init__(self, version_string):
        self.versionString = version_string
        self.version = []
        self.rc = StringVersion()
        self.extra = StringVersion()

        # Split array into version numbers, RC and Extraversion
        parts = self.versionDelimiter.split(version_string)

        # Get versions
        while len(parts):
            if parts[0].isdigit():
                self.version.append(parts.pop(0))
            else:
                break

        # Remove trailing '.0's'
        while self.version[-1] == 0:
            self.version.pop()

        # Get optional RC version
        if len(parts) and re.compile('^rc[0-9]+$').match(parts[0]):
            self.rc = StringVersion(parts.pop(0))

        # Get optional Extraversion
        if len(parts):
            self.extra = StringVersion(parts.pop(0))

        # This should be the end now
        if len(parts):
            raise Exception('Unable to parse version string: ' + version_string)

    def base_string(self, num=-1):
        """
        Returns the shortest possible version string of the base version (3.12.0-rc4-rt5 -> 3.12)

        :param num: Number of versionnumbers (e.g. KernelVersion('1.2.3.4').base_string(2) returns '1.2'
        :return: Base string
        """
        if num == -1:
            return ".".join(map(str, self.version))
        else:
            return ".".join(map(str, self.version[0:num]))

    def base_version_equals(self, other, num):
        """
        :param other: Other KernelVersion to compare against
        :param num: Number of subversions to be equal
        :return: True or false

        Examples:
        KernelVersion('3.12.0-rc4-rt5').baseVersionEquals(KernelVersion('3.12'), 3) = true ( 3.12 is the same as 3.12.0)
        KernelVersion('3.12.0-rc4-rt5').baseVersionEquals(KernelVersion('3.12.1'), 3) = false
        """

        left = self.version[0:num]
        right = other.version[0:num]

        # Fillup trailing zeros up to num. This is necessary, as we want to be able to compare versions like
        #   3.12.0     , 3
        #   3.12.0.0.1 , 3
        while len(left) != num:
            left.append(0)

        while len(right) != num:
            right.append(0)

        return left == right

    def __lt__(self, other):
        """
        :param other: KernelVersion to compare against
        :return: Returns True, if the left hand version is an older version
        """
        l = LooseVersion(self.base_string())
        r = LooseVersion(other.base_string())

        if l < r:
            return True
        elif l > r:
            return False

        # Version numbers equal so far. Check RC String
        # A version without a RC-String is the newer one
        if self.rc < other.rc:
            return True
        elif other.rc < self.rc:
            return False

        # We do have the same RC Version. Now check the extraversion
        # The one having an extraversion is considered to be the newer one
        return self.extra < other.extra

    def __str__(self):
        """
        :return: Minimum possible version string
        """
        return self.base_string() + str(self.rc) + str(self.extra)

    def __repr__(self):
        return str(self)


class VersionPoint:
    def __init__(self, commit, version, release_date):
        self.commit = commit
        self.version = version
        self.release_date = release_date


class Commit:
    def __init__(self, repo, hash, cache=True):
        self.hash = hash

        if cache:
            self.subject()
            self.body()

    def subject(self):
        try:
            self._subject
        except AttributeError:
            self._subject = repo.git.show('--pretty=format:%s', self.hash, stdout_as_string=False)
        return self._subject

    def body(self):
        try:
            self._body
        except AttributeError:
            self._body = repo.git.show('--pretty=format:%b', self.hash, stdout_as_string=False)
        return self._body


class PatchStack:
    def __init__(self, repo, base, patch, cache=True):
        self.base = base
        self.patch = patch
        self.patch_version = KernelVersion(patch.version)

        # get number of commits between baseversion and rtversion
        hashes = get_commit_hashes(repo, base.commit, patch.commit)
        self.commit_log = [Commit(repo, i, cache) for i in hashes]

    def __lt__(self, other):
        return self.patch_version < other.patch_version

    def num_commits(self):
        return len(self.commit_log)

    def __repr__(self):
        return self.patch.version + ' (' + str(self.num_commits()) + ')'


def get_date_of_commit(repo, commit):
    """
    :param repo: Git Repository
    :param commit: Commit Tag (e.g. v4.3 or SHA hash)
    :return: Author Date in format "YYYY-MM-DD"
    """
    return repo.git.log('--pretty=format:%ad', '--date=short', '-1', commit)


def get_commit_hashes(repo, start, end):
    hashes = repo.git.log('--pretty=format:%H', start + '...' + end)
    hashes = hashes.split('\n')
    return hashes


def __patch_stack_helper(repo, base_patch, cache):
    print('Working on ' + base_patch[1].version + '...')
    return PatchStack(repo, *base_patch, cache=cache)


def parse_patch_stack_definition(repo, definition_filename, cache):

    retval = []
    csv.register_dialect('patchstack', delimiter=' ', quoting=csv.QUOTE_NONE)

    with open(definition_filename) as f:
        reader = csv.DictReader(filter(lambda row: row[0] != '#', f),  # Skip lines beginning with #
                                dialect='patchstack')
        for row in reader:
            base = VersionPoint(row['BaseCommit'],
                                row['BaseVersion'],
                                row['BaseReleaseDate'])

            patch = VersionPoint(row['BranchName'],
                                 row['PatchVersion'],
                                 row['PatchReleaseDate'])

            retval.append((base, patch))


    # Map tuple of (base,patch) to PatchStack
    pool = Pool(cpu_count())
    retval = pool.map(functools.partial(__patch_stack_helper, repo, cache=cache), retval)

    # sort by patch version number
    retval.sort()
    return retval
