import sys

with open('db.py', 'r') as f:
    db_content = f.read()
db_content = db_content.replace('conn = sqlite3.connect(str(DB_PATH))', 'conn = sqlite3.connect(str(DB_PATH), timeout=60.0)')
with open('db.py', 'w') as f:
    f.write(db_content)

with open('main.py', 'r') as f:
    main_content = f.read()

replacement = '''    logger.info(f"[{tic_id}] 1. Ingestion")
    lcs = get_lightcurves(tic_id)
    if not lcs:
        update_status(tic_id, "NO_DATA")
        logger.info(f"[{tic_id}] NO_DATA")
        return
        
    lc_flat, lc_unflat = lcs
    ra, dec = lc_unflat.ra, lc_unflat.dec
    upsert_target(tic_id, tic_id, ra, dec, "PROCESSING")
    
    logger.info(f"[{tic_id}] 2. BLS Engine")
    bls_res = run_bls(lc_flat)
    
    logger.info(f"[{tic_id}] 3. Lomb-Scargle Engine")
    ls_res = run_lomb_scargle(lc_unflat)
    
    logger.info(f"[{tic_id}] 4. Vetting")
    category, best_res = vet_signals(bls_res, ls_res, lc_flat, lc_unflat)
    
    if category == "FALSE_POSITIVE":
        update_status(tic_id, "FALSE_POSITIVE")
        purge_cache_for_target(tic_id)
        logger.info(f"[{tic_id}] Finished: FALSE_POSITIVE")
        return
        
    logger.info(f"[{tic_id}] 5. Catalog Check")
    is_known, known_label = check_catalog(ra, dec, category, best_res.get('period', 0))
    final_status = get_final_status(category, is_known, known_label)
    
    update_status(tic_id, final_status)
    save_signal(tic_id, category, best_res)
    logger.info(f"[{tic_id}] Finished: {final_status}")
    
    if "UNRECORDED" in final_status:
        plot_path = save_diagnostic_plot(tic_id, final_status, lc_flat, lc_unflat, bls_res, ls_res)
        dispatch_alert(tic_id, final_status, best_res, plot_path)
    else:
        purge_cache_for_target(tic_id)'''

old_str = '''    # 1. Ingestion
    lcs = get_lightcurves(tic_id)
    if not lcs:
        update_status(tic_id, "NO_DATA")
        return
        
    lc_flat, lc_unflat = lcs
    ra, dec = lc_unflat.ra, lc_unflat.dec
    upsert_target(tic_id, tic_id, ra, dec, "PROCESSING")
    
    # 2. Analysis Engines
    bls_res = run_bls(lc_flat)
    ls_res = run_lomb_scargle(lc_unflat)
    
    # 3. Vetting
    category, best_res = vet_signals(bls_res, ls_res, lc_flat, lc_unflat)
    
    if category == "FALSE_POSITIVE":
        update_status(tic_id, "FALSE_POSITIVE")
        purge_cache_for_target(tic_id)
        return
        
    # 4. Catalog Check
    is_known, known_label = check_catalog(ra, dec, category, best_res.get('period', 0))
    final_status = get_final_status(category, is_known, known_label)
    
    update_status(tic_id, final_status)
    save_signal(tic_id, category, best_res)
    
    if "UNRECORDED" in final_status:
        # 5. Visualize
        plot_path = save_diagnostic_plot(tic_id, final_status, lc_flat, lc_unflat, bls_res, ls_res)
        
        # 6. Alert
        dispatch_alert(tic_id, final_status, best_res, plot_path)
    else:
        # Known object, purge raw data to save space
        purge_cache_for_target(tic_id)'''

if old_str in main_content:
    new_main = main_content.replace(old_str, replacement)
    with open('main.py', 'w') as f:
        f.write(new_main)
    print('main.py successfully patched.')
else:
    print('Could not find the target block in main.py.')
