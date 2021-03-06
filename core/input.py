import configparser
from pathlib import Path
from typing import Tuple
from core.db.crud import (read_asset_collection,
                          read_vulnerability_model,
                          LOSSCATEGORY_OBJECT_MAPPING)
from core.parsers import ASSETS_COLS_MAPPING
from core.utils import create_file_pointer

from sqlalchemy.orm import Session
from esloss.datamodel.asset import Asset

import io
import pandas as pd


def create_vulnerability_input(
    vulnerability_model_oid: int,
    session: Session,
    template_name: Path = Path('core/templates/vulnerability.xml')) \
        -> io.StringIO:
    """
    Create an in memory vulnerability xml file for OpenQuake.

    :param vulnerability_model_oid: oid of the VulnerabilityModel to be used.
    :param session: SQLAlchemy database session.
    :param template_name: Template to be used for the vulnerability file.
    :returns: Filepointer for exposure xml and one for csv list of assets.
    """

    vulnerability_model = read_vulnerability_model(
        vulnerability_model_oid, session)

    data = vulnerability_model._asdict()
    data['_type'] = next((k for k, v in LOSSCATEGORY_OBJECT_MAPPING.items()
                          if v.__name__.lower() == data['_type']))
    data['vulnerabilityfunctions'] = []

    for vf in vulnerability_model.vulnerabilityfunctions:
        vf_dict = vf._asdict()
        vf_dict['lossratios'] = [lr._asdict() for lr in vf.lossratios]
        data['vulnerabilityfunctions'].append(vf_dict)

    return create_file_pointer(template_name, data=data)


def create_exposure_input(
    asset_collection_oid: int,
    session: Session,
    template_name: Path = Path('core/templates/exposure.xml'),
    assets_csv_name: Path = Path('exposure_assets.csv')) \
        -> Tuple[io.StringIO, io.StringIO]:
    """
    Creates in-memory exposure input files for OpenQuake.

    :param asset_collection_oid: oid of the AssetCollection to be used.
    :param session: SQLAlchemy database session.
    :param template_name: Template to be used for the exposure file.
    :returns: Filepointer for exposure xml and one for csv list of assets.
    """

    asset_collection = read_asset_collection(asset_collection_oid, session)
    data = asset_collection._asdict()

    data['assets_csv_name'] = assets_csv_name.name
    data['costtypes'] = [c._asdict() for c in asset_collection.costtypes]
    data['tagnames'] = {
        agg.type: agg.name for agg in asset_collection.aggregationtags}

    exposure_xml = create_file_pointer(template_name, data=data)

    exposure_df = assets_to_dataframe(asset_collection.assets)

    exposure_csv = io.StringIO()
    exposure_df.to_csv(exposure_csv)
    exposure_csv.seek(0)
    exposure_csv.name = assets_csv_name.name

    return (exposure_xml, exposure_csv)


def assets_to_dataframe(assets: list[Asset]) -> pd.DataFrame:
    """
    Parses a list of Asset objects to a DataFrame.
    """

    assets_df = pd.DataFrame([x._asdict() for x in assets]).set_index('_oid')

    sites_df = pd.DataFrame([x.site._asdict() for x in assets])[
        ['longitude', 'latitude']]

    aggregationtags_df = pd.DataFrame(map(
        lambda asset: {tag.type: tag.name for tag in asset.aggregationtags},
        assets))

    result_df = pd.concat([assets_df,
                           sites_df.set_index(assets_df.index),
                           aggregationtags_df.set_index(assets_df.index)],
                          axis=1)

    selector = {**{'longitude': 'lon', 'latitude': 'lat'},
                **{v: k for k, v in ASSETS_COLS_MAPPING.items()},
                **{k: k for k in aggregationtags_df.columns}}

    result_df = result_df.rename(columns=selector)[[*selector.values()]] \
        .dropna(axis=1, how='all') \
        .fillna(0)
    result_df.index.name = 'id'

    return result_df


def assemble_calculation_input(job: configparser.ConfigParser,
                               session: Session) -> list[io.StringIO]:

    calculation_files = []

    exposure_xml, exposure_csv = create_exposure_input(
        job['exposure']['exposure_file'], session)
    exposure_xml.name = 'exposure.xml'
    job['exposure']['exposure_file'] = exposure_xml.name

    calculation_files.extend([exposure_xml, exposure_csv])

    for k, v in job['vulnerability'].items():
        xml = create_vulnerability_input(v, session)
        xml.name = "{}.xml".format(k.replace('_file', ''))
        job['vulnerability'][k] = xml.name
        calculation_files.append(xml)

    for k, v in job['hazard'].items():
        with open(v, 'r') as f:
            file = io.StringIO(f.read())
        file.name = Path(v).name
        job['hazard'][k] = file.name
        calculation_files.append(file)

    job_file = create_job_file(job)
    job_file.name = 'job.ini'
    calculation_files.append(job_file)

    return calculation_files


def create_job_file(settings: configparser.ConfigParser) -> io.StringIO:
    job_ini = io.StringIO()
    settings.write(job_ini)
    job_ini.seek(0)

    return job_ini
