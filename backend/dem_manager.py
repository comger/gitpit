import os
import glob
import rasterio
from shapely.geometry import Point, box
import dem_stitcher
import math

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LOCAL_DEMS_DIR = os.path.join(DATA_DIR, "local_dems")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

os.makedirs(LOCAL_DEMS_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

def get_resolution_meters(filepath: str, lat: float) -> float:
    """Read resolution from GeoTIFF and convert degrees to meters if necessary"""
    with rasterio.open(filepath) as src:
        res = src.res[0]
        # Check if CRS is geographic (degrees)
        if src.crs and src.crs.is_geographic:
            # 1 degree of latitude is roughly 111,320 meters
            # 1 degree of longitude is 111,320 * cos(lat) meters
            # Use an average approximation for the tile
            res_meters = res * 111320 * math.cos(math.radians(lat))
            return round(abs(res_meters), 1)
        return round(abs(res), 1)

def get_dem_for_point(lat: float, lon: float) -> tuple[str, str, float]:
    """
    Finds a suitable DEM for the requested point.
    Returns: (file_path, dem_source, resolution_meters)
    where dem_source is "local" or "online"
    """
    point = Point(lon, lat)
    
    # 1. Check local DEMs first
    for filepath in glob.glob(os.path.join(LOCAL_DEMS_DIR, "*.tif")):
        try:
            with rasterio.open(filepath) as src:
                bounds = src.bounds
                geom = box(bounds.left, bounds.bottom, bounds.right, bounds.top)
                if geom.contains(point):
                    return filepath, "local", get_resolution_meters(filepath, lat)
        except Exception as e:
            print(f"Error reading local DEM {filepath}: {e}")
            continue
            
    # 2. Fallback to online DEM (GLO-30)
    # Define a bounding box around the point.
    pad = 0.2
    bbox = [lon - pad, lat - pad, lon + pad, lat + pad]
    
    cache_filename = f"glo30_{bbox[0]:.2f}_{bbox[1]:.2f}_{bbox[2]:.2f}_{bbox[3]:.2f}.tif"
    cache_path = os.path.join(CACHE_DIR, cache_filename)
    
    if os.path.exists(cache_path):
        return cache_path, "online (cached)", get_resolution_meters(cache_path, lat)
        
    print(f"Fetching online DEM for bbox {bbox}...")
    X, profile = dem_stitcher.stitch_dem(
        bbox,
        dem_name='glo_30',
        dst_ellipsoidal_height=False,
        dst_area_or_point='Area'
    )
    
    profile.update(driver='GTiff')
    
    with rasterio.open(cache_path, 'w', **profile) as dst:
        dst.write(X, 1)
        
    return cache_path, "online", get_resolution_meters(cache_path, lat)

def get_dem_for_bbox(min_lat: float, min_lon: float, max_lat: float, max_lon: float, pad: float = 0.05) -> tuple[str, str, float]:
    """
    Finds a suitable DEM for an expanded bounding box.
    """
    # Expand the bounding box by the padding (approx 5km for 0.05)
    bbox = [min_lon - pad, min_lat - pad, max_lon + pad, max_lat + pad]
    center_lat = (min_lat + max_lat) / 2.0
    
    # Optional logic: could check if local DEM contains the entire bbox. 
    # For now, to keep it simple, we prioritize online stitching for arbitrary bboxes 
    # to avoid complex merging of multiple local tif tiles. 
    # But let's check if the center point is in local DEM and use it if it's large enough.
    center_point = Point((min_lon + max_lon) / 2.0, center_lat)
    for filepath in glob.glob(os.path.join(LOCAL_DEMS_DIR, "*.tif")):
        try:
            with rasterio.open(filepath) as src:
                geom = box(*src.bounds)
                req_geom = box(*bbox)
                # If local DEM fully covers the requested expanded bbox
                if geom.contains(req_geom):
                    return filepath, "local", get_resolution_meters(filepath, center_lat)
        except Exception:
            continue
            
    cache_filename = f"glo30_bbox_{bbox[0]:.2f}_{bbox[1]:.2f}_{bbox[2]:.2f}_{bbox[3]:.2f}.tif"
    cache_path = os.path.join(CACHE_DIR, cache_filename)
    
    if os.path.exists(cache_path):
        return cache_path, "online (cached)", get_resolution_meters(cache_path, center_lat)
        
    print(f"Fetching online DEM for network bbox {bbox}...")
    X, profile = dem_stitcher.stitch_dem(
        bbox,
        dem_name='glo_30',
        dst_ellipsoidal_height=False,
        dst_area_or_point='Area'
    )
    
    profile.update(driver='GTiff')
    
    with rasterio.open(cache_path, 'w', **profile) as dst:
        dst.write(X, 1)
        
    return cache_path, "online", get_resolution_meters(cache_path, center_lat)
