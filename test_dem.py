import dem_stitcher
import rasterio

bounds = [116.3, 39.9, 116.4, 40.0]
try:
    X, p = dem_stitcher.stitch_dem(bounds, dem_name='glo_30', dst_ellipsoidal_height=False, dst_area_or_point='Area')
    print("DEM Stitcher success")
    print(X.shape)
except Exception as e:
    print("DEM Stitcher failed:", e)
