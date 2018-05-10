# coding=utf-8
"""Tests related to auto distributions."""
import hashlib
import unittest
from urllib.parse import urljoin

from requests import HTTPError

from pulp_smash import api, config, utils
from pulp_smash.constants import FILE_FEED_URL, FILE_URL
from pulp_smash.tests.pulp3.constants import (
    DISTRIBUTION_PATH,
    FILE_CONTENT_PATH,
    FILE_PUBLISHER_PATH,
    FILE_REMOTE_PATH,
    REPO_PATH,
)
from pulp_smash.tests.pulp3.file.api_v3.utils import gen_publisher
from pulp_smash.tests.pulp3.file.utils import populate_pulp
from pulp_smash.tests.pulp3.file.utils import set_up_module as setUpModule  # pylint:disable=unused-import
from pulp_smash.tests.pulp3.utils import (
    gen_distribution,
    gen_remote,
    gen_repo,
    get_added_content,
    get_auth,
    get_versions,
    publish,
    sync,
)


class AutoDistributionTestCase(unittest.TestCase):
    """Test auto distribution."""

    @classmethod
    def setUpClass(cls):
        """Create class-wide variables.

        Add content to Pulp.
        """
        cls.cfg = config.get_config()
        cls.client = api.Client(cls.cfg, api.json_handler)
        cls.client.request_kwargs['auth'] = get_auth()
        populate_pulp(cls.cfg)
        cls.contents = cls.client.get(FILE_CONTENT_PATH)['results'][:2]

    def test_repo_auto_distribution(self):
        """Test auto distribution of a repository.

        This test targets the following issue:

        * `Pulp Smash #947 <https://github.com/PulpQE/pulp-smash/issues/947>`_

        Do the following:

        1. Create a repository that has at least one repository version.
        2. Create a publisher.
        3. Create a distribution and set the repository and publishera to the
           previous created ones.
        4. Create a publication using the latest repository version.
        5. Assert that the previous distribution has a  ``publication`` set as
           the one created in step 4.
        6. Create a new repository version by adding content to the repository.
        7. Create another publication using the just created repository
           version.
        8. Assert that distribution now has the ``publication`` set to the
           publication created in the step 7.
        9. Verify that content added in the step 7 is now available to download
           from distribution, and verify that the content unit has the same
           checksum when fetched directly from Pulp-Fixtures.
        """
        self.assertGreaterEqual(len(self.contents), 2, self.contents)

        # Create a repository.
        repo = self.client.post(REPO_PATH, gen_repo())
        self.addCleanup(self.client.delete, repo['_href'])
        self.client.post(
            repo['_versions_href'],
            {'add_content_units': [self.contents[0]['_href']]}
        )
        repo = self.client.get(repo['_href'])

        # Create publisher.
        publisher = self.client.post(FILE_PUBLISHER_PATH, gen_publisher())
        self.addCleanup(self.client.delete, publisher['_href'])

        # Create a distribution
        body = gen_distribution()
        body['repository'] = repo['_href']
        body['publisher'] = publisher['_href']
        distribution = self.client.post(DISTRIBUTION_PATH, body)
        self.addCleanup(self.client.delete, distribution['_href'])
        last_version_href = get_versions(repo)[-1]['_href']
        publication = publish(
            self.cfg, publisher, repo, last_version_href)
        self.addCleanup(self.client.delete, publication['_href'])
        distribution = self.client.get(distribution['_href'])

        # Assert that distribution was updated as per step 5.
        self.assertEqual(distribution['publication'], publication['_href'])

        # Create a new repository version.
        self.client.post(
            repo['_versions_href'],
            {'add_content_units': [self.contents[1]['_href']]}
        )
        repo = self.client.get(repo['_href'])
        last_version_href = get_versions(repo)[-1]['_href']
        publication = publish(
            self.cfg, publisher, repo, last_version_href)
        self.addCleanup(self.client.delete, publication['_href'])
        distribution = self.client.get(distribution['_href'])

        # Assert that distribution was updated as per step 8.
        self.assertEqual(distribution['publication'], publication['_href'])
        unit_path = get_added_content(
            repo, last_version_href)['results'][0]['relative_path']
        unit_url = self.cfg.get_hosts('api')[0].roles['api']['scheme']
        unit_url += '://' + distribution['base_url'] + '/'
        unit_url = urljoin(unit_url, unit_path)

        self.client.response_handler = api.safe_handler
        pulp_hash = hashlib.sha256(
            self.client.get(unit_url).content
        ).hexdigest()
        fixtures_hash = hashlib.sha256(
            utils.http_get(urljoin(FILE_URL, unit_path))
        ).hexdigest()

        # Verify checksum. Step 9.
        self.assertEqual(fixtures_hash, pulp_hash)


class SetupAutoDistributionTestCase(unittest.TestCase):
    """Verify the set up of parameters related to auto distribution."""

    def test_all(self):
        """Verify the set up of parameters related to auto distribution.

        This test targets the following issues:

        * `Pulp #3295 <https://pulp.plan.io/issues/3295>`_
        * `Pulp #3392 <https://pulp.plan.io/issues/3392>`_
        * `Pulp #3394 <https://pulp.plan.io/issues/3394>`_
        * `Pulp #3671 <https://pulp.plan.io/issues/3671>`_
        * `Pulp Smash #883 <https://github.com/PulpQE/pulp-smash/issues/883>`_
        * `Pulp Smash #917 <https://github.com/PulpQE/pulp-smash/issues/917>`_
        """
        cfg = config.get_config()
        client = api.Client(cfg, api.json_handler)
        client.request_kwargs['auth'] = get_auth()
        repo = client.post(REPO_PATH, gen_repo())
        self.addCleanup(client.delete, repo['_href'])
        body = gen_distribution()

        # Create a distribution with a repository but no publisher.
        body['repository'] = repo['_href']
        with self.assertRaises(HTTPError):
            client.post(DISTRIBUTION_PATH, body)

        # Create a distribution with a repository and publisher.
        publisher = client.post(FILE_PUBLISHER_PATH, gen_publisher())
        self.addCleanup(client.delete, publisher['_href'])
        body['publisher'] = publisher['_href']
        distribution = client.post(DISTRIBUTION_PATH, body)
        self.addCleanup(client.delete, distribution['_href'])

        # Update distribution`s repository to None.
        distribution['repository'] = None
        with self.assertRaises(HTTPError):
            client.patch(distribution['_href'], distribution)
        distribution = client.get(distribution['_href'])
        self.assertIsNotNone(distribution['repository'], distribution)

        # Update distribution`s publisher to None.
        distribution['publisher'] = None
        with self.assertRaises(HTTPError):
            client.patch(distribution['_href'], distribution)
        distribution = client.get(distribution['_href'])
        self.assertIsNotNone(distribution['publisher'], distribution)

        # Update distributions` publisher and repository to None.
        distribution['publisher'] = None
        distribution['repository'] = None
        distribution = client.patch(distribution['_href'], distribution)
        self.assertIsNone(distribution['publisher'], distribution)
        self.assertIsNone(distribution['repository'], distribution)

        # Publish the repository. Assert that distribution does not point to
        # the new publication.
        body = gen_remote(urljoin(FILE_FEED_URL, 'PULP_MANIFEST'))
        remote = client.post(FILE_REMOTE_PATH, body)
        self.addCleanup(client.delete, remote['_href'])
        sync(cfg, remote, repo)
        publication = publish(cfg, publisher, repo)
        self.addCleanup(client.delete, publication['_href'])
        self.assertNotEqual(distribution['publication'], publication['_href'])
