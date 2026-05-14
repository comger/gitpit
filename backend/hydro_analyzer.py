import json
import numpy as np
from pysheds.grid import Grid
from pyproj import Geod

def _compute_stream_order_stats(grid, fdir, acc, dem, dirmap, snap_threshold):
    """
    Classify stream segments into 3 orders based on accumulation thresholds,
    then compute average length (km) and average slope (m/m) for each order.
    
    Order classification (by accumulation rank):
      Order 1 (headwater): acc in [snap_threshold, Q33)
      Order 2 (tributary): acc in [Q33, Q66)
      Order 3 (main stem): acc >= Q66
    """
    geod = Geod(ellps="WGS84")
    
    stream_mask = acc > snap_threshold
    stream_acc_vals = acc[stream_mask]
    if stream_acc_vals.size == 0:
        return []
    
    q33 = float(np.percentile(stream_acc_vals, 33))
    q66 = float(np.percentile(stream_acc_vals, 66))
    
    order_thresholds = [
        (1, snap_threshold, q33),
        (2, q33,            q66),
        (3, q66,            float(stream_acc_vals.max()) + 1),
    ]
    
    # Get cell coordinates from grid
    try:
        rows, cols = np.where(stream_mask)
        # pysheds stores affine transform in grid.affine (or grid.transform)
        transform = grid.affine
        # Convert pixel centers to lon/lat
        lons = transform.c + (cols + 0.5) * transform.a
        lats = transform.f + (rows + 0.5) * transform.e
        acc_vals = acc[rows, cols]
        dem_vals = dem[rows, cols]
    except Exception as e:
        import traceback; traceback.print_exc()
        print("Error in _compute_stream_order_stats:", e)
        return []
    
    results = []
    for order, lo, hi in order_thresholds:
        sel = (acc_vals > lo) & (acc_vals <= hi)
        if not np.any(sel):
            continue
        sel_lons = lons[sel]
        sel_lats = lats[sel]
        sel_elev = dem_vals[sel]
        
        n = len(sel_lons)
        if n == 0:
            continue
            
        # Average cell size approximation
        dx_deg = abs(transform.a)
        dy_deg = abs(transform.e)
        center_lat = float(np.nanmean(sel_lats))
        cell_w_m = dx_deg * 111320.0 * np.cos(np.radians(center_lat))
        cell_h_m = dy_deg * 111320.0
        # A simple approximation for the average flow path length through a pixel
        cell_size_m = np.sqrt(cell_w_m * cell_h_m)
        
        total_length_m = n * cell_size_m
        avg_length_km = (total_length_m / 1000.0)
        
        s_elev = sel_elev
        valid_elev = s_elev[~np.isnan(s_elev)]
        if valid_elev.size > 1 and total_length_m > 0:
            elev_drop = float(np.nanmax(valid_elev) - np.nanmin(valid_elev))
            avg_slope = elev_drop / total_length_m
        else:
            avg_slope = 0.0
        
        results.append({
            "order": order,
            "cell_count": int(n),
            "total_length_km": round(avg_length_km, 2),
            "elev_drop_m": round(float(np.nanmax(s_elev) - np.nanmin(s_elev)), 1) if s_elev.size > 1 else 0.0,
            "avg_slope": round(avg_slope, 5),
            "avg_slope_pct": round(avg_slope * 100, 3),
        })
    
    return results


def calculate_catchment(dem_path: str, lat: float, lon: float, snap_threshold: int = 100):
    """
    Computes the catchment area and flow path for a given point.
    Returns:
        dict: {
            "catchment": FeatureCollection,
            "flow_path": FeatureCollection,
            "area_km2": float
        }
    """
    grid = Grid.from_raster(dem_path)
    dem = grid.read_raster(dem_path)
    
    # 1. Fill depressions
    pit_filled_dem = grid.fill_depressions(dem)
    
    # 2. Resolve flats
    flooded_dem = grid.resolve_flats(pit_filled_dem)
    
    # 3. Flow direction (D8)
    # Using classic ESRI D8 mapping
    dirmap = (64, 128, 1, 2, 4, 8, 16, 32)
    fdir = grid.flowdir(flooded_dem, dirmap=dirmap)
    
    # 4. Flow accumulation
    acc = grid.accumulation(fdir, dirmap=dirmap)
    
    # 5. Snap pour point
    # Find the nearest cell with accumulation > snap_threshold
    try:
        x_snap, y_snap, dist = grid.snap_to_mask(acc > snap_threshold, (lon, lat), return_dist=True)
        # Using Pythagorean distance on coordinates (degrees).
        # 200 meters is roughly 0.002 degrees.
        if dist > 0.002:
            x_snap, y_snap = lon, lat
    except Exception as e:
        # Fallback if no nearby high accumulation cell is found
        x_snap, y_snap = lon, lat
        
    # 6. Delineate catchment
    catch = grid.catchment(x=x_snap, y=y_snap, fdir=fdir, dirmap=dirmap, 
                           xytype='coordinate')
    
    # Clip the bounding box to the catchment 
    grid.clip_to(catch)
    clipped_catch = grid.view(catch)
    
    # 7. Convert Catchment to GeoJSON
    # Extract polygon from the raster mask
    # Need to import rasterio.features here or use pysheds built ins
    catch_polygons = grid.polygonize()
    # polygonize returns a generator of (polygon, value). We want value == 1 (or the catchment ID).
    # Since we clipped to catchment, everything nonzero is our catchment.
    catchment_geom = None
    for poly, val in catch_polygons:
        if val:
            catchment_geom = poly
            break
            
    # Calculate Area using WGS 84 ellipsoid
    geod = Geod(ellps="WGS84")
    # Using shapely to calculate geodesic area
    from shapely.geometry import shape
    area_km2 = 0.0
    max_elev = 0.0
    min_elev = 0.0
    delta_h = 0.0
    
    if catchment_geom:
        poly_shape = shape(catchment_geom)
        area, perimeter = geod.geometry_area_perimeter(poly_shape)
        area_km2 = abs(area) / 1e6
        
        # Calculate elevation drop
        catch_mask = (clipped_catch > 0)
        dem_view = grid.view(dem)
        valid_elevations = dem_view[catch_mask]
        
        if valid_elevations.size > 0:
            max_elev = float(np.nanmax(valid_elevations))
            min_elev = float(np.nanmin(valid_elevations))
            delta_h = max_elev - min_elev

    # 8. Extract river network
    branches = grid.extract_river_network(fdir, acc > snap_threshold, dirmap=dirmap)
    
    # 9. Compute stream order statistics
    try:
        stream_order_stats = _compute_stream_order_stats(
            grid, grid.view(fdir), grid.view(acc), grid.view(dem), dirmap, snap_threshold
        )
    except Exception as e:
        import traceback; traceback.print_exc()
        stream_order_stats = []
    
    # Branches is a dict that looks like GeoJSON FeatureCollection
    
    return {
        "catchment": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": catchment_geom,
                "properties": {"area_km2": area_km2}
            }] if catchment_geom else []
        },
        "flow_path": branches,
        "area_km2": area_km2,
        "max_elev": max_elev,
        "min_elev": min_elev,
        "delta_h": delta_h,
        "stream_order_stats": stream_order_stats,
        "pour_point": {
            "type": "Point",
            "coordinates": [x_snap, y_snap]
        }
    }


def analyze_network(dem_path: str, threshold: int = 500):
    """
    Computes the full river network for a given DEM using an accumulation threshold.
    Returns:
        dict: {
            "flow_path": FeatureCollection
        }
    """
    grid = Grid.from_raster(dem_path)
    dem = grid.read_raster(dem_path)
    
    # 1. Fill depressions
    pit_filled_dem = grid.fill_depressions(dem)
    
    # 2. Resolve flats
    flooded_dem = grid.resolve_flats(pit_filled_dem)
    
    # 3. Flow direction (D8)
    dirmap = (64, 128, 1, 2, 4, 8, 16, 32)
    fdir = grid.flowdir(flooded_dem, dirmap=dirmap)
    
    # 4. Flow accumulation
    acc = grid.accumulation(fdir, dirmap=dirmap)
    
    # 5. Extract river network for the entire grid
    branches = grid.extract_river_network(fdir, acc > threshold, dirmap=dirmap)
    
    return {
        "flow_path": branches
    }
