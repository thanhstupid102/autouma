// ---------------------------------------------------------------------------
// Master data
// ---------------------------------------------------------------------------

export interface MasterDataStatus {
  master_mdb_path?: string
  exists: boolean
  generated?: boolean
  generation_error?: string
  access_error?: string
  [k: string]: unknown
}

export interface SetMasterDataPathBody {
  master_mdb_path: string
}
