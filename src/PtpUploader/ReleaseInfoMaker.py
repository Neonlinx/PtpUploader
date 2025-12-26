import argparse
import os
import re

from pathlib import Path
from typing import Optional

import django

from pyrosimple.util import metafile


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PtpUploader.web.settings")
django.setup()

from PtpUploader import Ptp
from PtpUploader.MyGlobals import MyGlobals
from PtpUploader.PtpUploaderException import PtpUploaderException
from PtpUploader.ReleaseDescriptionFormatter import ReleaseDescriptionFormatter
from PtpUploader.ReleaseInfo import ReleaseInfo
from PtpUploader.Settings import Settings
from PtpUploader.Tool import Mktor


class ReleaseInfoMaker:
    def __init__(self, path: os.PathLike):
        self.path = Path(path)
        self.release_info = ReleaseInfo()
        self.release_info.ReleaseDownloadPath = str(self.path)
        self.release_info.ReleaseUploadPath = str(self.path)
        self.release_info.ReleaseName = self.path.stem
        self.release_info.Logger = MyGlobals.Logger

    @property
    def description_path(self) -> Path:
        return self.path.parent / f"PTP {self.release_info.ReleaseName}.release description.txt"

    @property
    def torrent_path(self) -> Path:
        return self.path.parent / f"PTP {self.release_info.ReleaseName}.torrent"

    def collect_files(self) -> None:
        self.release_info.SetIncludedFileList()
        self.detect_images()

    def detect_images(self) -> None:
        for file in self.release_info.AdditionalFiles() or []:
            if str(file).lower().endswith(".ifo"):
                self.release_info.Codec = "DVD5"
                return
        if self.path.is_dir() and "BDMV" in {f.name for f in self.path.iterdir()}:
            self.release_info.Codec = "BD25"

    def save_description(self, output_path: os.PathLike, create_screens: bool) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        formatter = ReleaseDescriptionFormatter(
            self.release_info, [], [], self.path.parent, create_screens
        )
        description = formatter.Format(includeReleaseName=True)
        self.release_info.Logger.info("Saving to description file %r", str(output_path))
        with output_path.open("w") as handle:
            handle.write(description)

    def _ensure_writable(self, path: Path, overwrite: bool, kind: str) -> None:
        if path.exists() and not overwrite:
            raise FileExistsError(f"Can't create {kind} because {path!s} already exists!")

    def make_release_info(
        self,
        create_torrent=True,
        create_screens=True,
        overwrite=False,
        setDescription: Optional[str] = None,
    ) -> None:
        self.collect_files()
        self._ensure_writable(self.description_path, overwrite, "release description")
        self.save_description(self.description_path, create_screens)
        if create_torrent:
            self._ensure_writable(self.torrent_path, overwrite, "torrent")
            Mktor.Make(MyGlobals.Logger, self.path, self.torrent_path)
            base_dir = (
                self.path.parent if self.release_info.SourceIsAFile() else self.path
            )
            MyGlobals.GetTorrentClient().AddTorrentSkipHashCheck(
                MyGlobals.Logger, self.torrent_path, base_dir
            )

    def set_description(self, target: str) -> None:
        if os.path.exists(target):
            meta = metafile.Metafile.from_file(Path(target))
            target = meta["comment"]
        if target and "torrentid=" in target:
            tID = re.search("torrentid=(\d+)", target)
            if not tID:
                raise PtpUploaderException("Unable to extract torrent id from target")
            tID = tID.group(1)
        else:
            raise PtpUploaderException("No torrent id present in target")
        Ptp.Login()
        self.release_info.Logger.info("Uploading description as a report to %s", tID)
        if not Settings.AntiCsrfToken:
            raise PtpUploaderException("No AntiCsrfToken found")
        with self.description_path.open("r") as fh:
            r = MyGlobals.session.post(
                "https://passthepopcorn.me/reportsv2.php?action=takereport",
                data={
                    "extra": fh.read(),
                    "torrentid": tID,
                    "categoryid": "1",
                    "type": "replacement description",
                    "submit": "true",
                    "AntiCsrfToken": Settings.AntiCsrfToken,
                },
            )
            r.raise_for_status()


def run():
    parser = argparse.ArgumentParser(
        description="PtpUploader Release Description Maker by TnS"
    )

    parser.add_argument(
        "--notorrent", action="store_true", help="skip creating and seeding the torrent"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite the description file if it already exists",
    )
    parser.add_argument(
        "--noscreens",
        action="store_true",
        help="skip creating and uploading screenshots",
    )
    # Hidden stub option to upload description directly to PTP
    parser.add_argument("--set-description", help=argparse.SUPPRESS, default=None)
    parser.add_argument("path", nargs=1, help="The file or directory to use")

    args = parser.parse_args()

    Settings.LoadSettings()
    MyGlobals.InitializeGlobals(Settings.WorkingPath)

    releaseInfoMaker = ReleaseInfoMaker(args.path[0])
    releaseInfoMaker.make_release_info(
        overwrite=args.force,
        create_torrent=(not args.notorrent),
        create_screens=(not args.noscreens),
        setDescription=args.set_description,
    )
    if args.set_description:
        releaseInfoMaker.set_description(args.set_description)


if __name__ == "__main__":
    run()
