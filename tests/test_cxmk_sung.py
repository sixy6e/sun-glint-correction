#!/usr/bin/env python3
"""
Unittests for the Cox and Munk algorithm:
    * if input szen, vzen, razi are not two-dimensional?
    * if dimension mismatch between szen, vzen, razi
    * if dimension mismatch between p_glint and vis_im
    * if wind_speed < 0
    * if any input data only contain a single value
"""

import pytest
import rasterio
import numpy as np

from pathlib import Path
from sungc import deglint
from sungc.algorithms import coxmunk_backend
from sungc.rasterio_funcs import load_singleband

from . import urd, create_halved_band

# specify the path to the odc_metadata.yaml of the test datasets
data_path = Path(__file__).parent / "data"
odc_meta_file = data_path / "ga_ls8c_aard_3-2-0_091086_2014-11-06_final.odc-metadata.yaml"

# specify the sub_product
sub_product = "lmbadj"


def test_cxmk_image():
    """
    Check that the generated deglinted band is nearly identical
    to the expected deglinted band
    """
    # Initiate the sunglint correction class
    g = deglint.GlintCorr(odc_meta_file, sub_product)

    # ------------------ #
    #    Cox and Munk    #
    # ------------------ #
    cxmk_xarrlist = g.cox_munk(
        vis_bands=["3"],
        wind_speed=5,
        water_val=5,
    )

    sungc_band = cxmk_xarrlist[0].lmbadj_green.values  # 3D array

    # path to expected sunglint corrected output from NIR subtraction
    exp_sungc_band = (
        data_path
        / "COX_MUNK"
        / "ga_ls8c_lmbadj_3-2-0_091086_2014-11-06_final_band03-deglint-600m.tif"
    )

    # ensure that all valid sungint corrected pixels match expected
    with rasterio.open(exp_sungc_band, "r") as exp_sungc_ds:
        urd_band = urd(sungc_band[0, :, :], exp_sungc_ds.read(1), exp_sungc_ds.nodata)
        assert urd_band.max() < 0.001


def test_glint_images():
    """
    Tes that the generated glint reflectance is nearly
    identical to expected glint reflectance
    """
    exp_glint_band = (
        data_path
        / "COX_MUNK"
        / "ga_ls8c_lmbadj_3-2-0_091086_2014-11-06_final_cm_glint.tif"
    )

    # Initiate the sunglint correction class
    g = deglint.GlintCorr(odc_meta_file, sub_product)

    vzen_file = g.find_file("satellite_view")
    szen_file = g.find_file("solar_zenith")
    razi_file = g.find_file("relative_azimuth")

    # load the required geometry images
    vzen_im, vzen_meta = load_singleband(vzen_file)
    szen_im, szen_meta = load_singleband(szen_file)
    razi_im, razi_meta = load_singleband(razi_file)
    cm_meta = vzen_meta.copy()

    # cox and munk:
    p_glint, p_fresnel = coxmunk_backend(
        view_zenith=vzen_im,
        solar_zenith=szen_im,
        relative_azimuth=razi_im,
        wind_speed=5,
        return_fresnel=False,
    )

    # convert p_glint & p_fresnel from np.float32 to np.int16
    p_nodata = cm_meta["nodata"]  # this is np.nan
    p_glint[p_glint != p_nodata] *= g.scale_factor
    p_glint[p_glint == p_nodata] = -999.0
    p_glint = np.array(p_glint, order="C", dtype=np.int16)

    # ensure that all valid sungint corrected pixels match expected
    with rasterio.open(exp_glint_band, "r") as eglint_ds:
        urd_glint = urd(p_glint, eglint_ds.read(1), eglint_ds.nodata)
        assert urd_glint.max() < 0.001


def test_cxmk_bands():
    """
    Ensure that the Cox and Munk module raises an
    Exception if the specified vis_band_id does not exist
    """
    g = deglint.GlintCorr(odc_meta_file, sub_product)

    with pytest.raises(Exception) as excinfo:
        g.cox_munk(
            vis_bands=["20"],  # this band id doesn't exist
            wind_speed=5,
            water_val=5,
        )
    assert "is missing from bands" in str(excinfo)


def test_nodata_band():
    """
    Ensure that the Cox and Munk module raises an
    Exception if the input band only contains nodata
    """
    g = deglint.GlintCorr(odc_meta_file, sub_product)

    with pytest.raises(Exception) as excinfo:
        g.cox_munk(
            vis_bands=["7"],  # dummy band only contains nodata (-999)
            wind_speed=5,
            water_val=5,
        )
    assert "only contains a single value" in str(excinfo)


def test_nodata_vzen(tmp_path):
    """
    Ensure that the Cox and Munk module raises an
    Exception if any of the solar-view geometry
    band only contains nodata. We will test this
    with the sensor view-zenith.
    """
    g = deglint.GlintCorr(odc_meta_file, sub_product)

    cxmk_dir = tmp_path / "COX_MUNK"
    cxmk_dir.mkdir()

    # create empty view-zenith tiff
    dum_vzen = cxmk_dir / "ga_ls8c_oa_3-2-0_091086_2014-11-06_final_DUMMY_view-zenith.tif"

    with rasterio.open(g.find_file("satellite_view"), "r") as vzen_ds:
        kwargs = vzen_ds.meta.copy()

        # write dummy geotiff
        nrows = vzen_ds.height
        ncols = vzen_ds.width
        dtype = np.dtype(kwargs["dtype"])
        nodata = kwargs["nodata"]  # np.nan

        arr = np.zeros([nrows, ncols], order="C", dtype=dtype)
        arr[:] = nodata

        with rasterio.open(dum_vzen, "w", **kwargs) as dst:
            dst.write(arr, 1)

    # specify dummy band
    with pytest.raises(Exception) as excinfo:
        g.cox_munk(
            vis_bands=["3"],
            vzen_file=dum_vzen,  # dummy band only contains nodata (np.nan)
            wind_speed=5,
            water_val=5,
        )
    assert "only contains a single value" in str(excinfo)


def test_geom_same_dims(tmp_path):
    """
    Ensure that the Cox and Munk module will raise an
    Exception if a view-solar geometry band does not
    have the same dimensions as the other bands.
    """
    g = deglint.GlintCorr(odc_meta_file, sub_product)

    cxmk_dir = tmp_path / "COX_MUNK"
    cxmk_dir.mkdir()

    # create a small view-zenith tiff
    resmpl_tifs, rio_meta = create_halved_band(g.find_file("satellite_view"), cxmk_dir)

    # cox_munk() should raise an Exception as vzen band does not
    # have the same shape as the solar-zenith and relative-azimuth
    # bands
    with pytest.raises(Exception) as excinfo:
        g.cox_munk(
            vis_bands=["3"],
            vzen_file=resmpl_tifs[0],
            wind_speed=5,
            water_val=5,
        )
    assert "Dimension mismatch" in str(excinfo)


def test_windspeed_lt0():
    """
    Ensure that the Cox and Munk module will raise an
    Exception if the wind speed < 0 m/s
    """
    g = deglint.GlintCorr(odc_meta_file, sub_product)

    with pytest.raises(Exception) as excinfo:
        g.cox_munk(
            vis_bands=["3"],
            wind_speed=-1,
            water_val=5,
        )
    assert "wind_speed must be greater than 0 m/s" in str(excinfo)
