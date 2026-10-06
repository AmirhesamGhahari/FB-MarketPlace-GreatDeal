locals {
  db_name = replace(var.app_name, "-", "_")
}

resource "aws_glue_catalog_database" "main" {
  name = local.db_name
}

resource "aws_glue_catalog_table" "fb_listings_raw" {
  name          = "fb_listings_raw"
  database_name = aws_glue_catalog_database.main.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"       = "parquet"
    "parquet.compression"  = "SNAPPY"
  }

  storage_descriptor {
    location      = "s3://${var.bucket_name}/raw/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    columns {
      name = "raw_id"
      type = "string"
    }
    columns {
      name = "pipeline_run_id"
      type = "string"
    }
    columns {
      name = "fb_listing_id"
      type = "string"
    }
    columns {
      name = "listing_url"
      type = "string"
    }
    columns {
      name = "title"
      type = "string"
    }
    columns {
      name = "description"
      type = "string"
    }
    columns {
      name = "price"
      type = "double"
    }
    columns {
      name = "currency"
      type = "string"
    }
    columns {
      name = "original_price"
      type = "double"
    }
    columns {
      name = "location_city"
      type = "string"
    }
    columns {
      name = "location_state"
      type = "string"
    }
    columns {
      name = "image_urls"
      type = "string"
    }
    columns {
      name = "is_sold"
      type = "boolean"
    }
    columns {
      name = "listed_at"
      type = "timestamp"
    }
    columns {
      name = "scraped_at"
      type = "timestamp"
    }
    columns {
      name = "search_query"
      type = "string"
    }
    columns {
      name = "fb_condition"
      type = "string"
    }
    columns {
      name = "delivery_types"
      type = "string"
    }
    columns {
      name = "is_highly_rated_seller"
      type = "boolean"
    }
  }

  partition_keys {
    name = "category_key"
    type = "string"
  }
  partition_keys {
    name = "run_date"
    type = "string"
  }
}

resource "aws_glue_catalog_table" "fb_listings_classified" {
  name          = "fb_listings_classified"
  database_name = aws_glue_catalog_database.main.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"       = "parquet"
    "parquet.compression"  = "SNAPPY"
  }

  storage_descriptor {
    location      = "s3://${var.bucket_name}/classified/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    columns {
      name = "classified_id"
      type = "string"
    }
    columns {
      name = "pipeline_run_id"
      type = "string"
    }
    columns {
      name = "fb_listing_id"
      type = "string"
    }
    columns {
      name = "classified_at"
      type = "timestamp"
    }
    columns {
      name = "llm_model"
      type = "string"
    }
    columns {
      name = "listing_type"
      type = "string"
    }
    columns {
      name = "product_brand"
      type = "string"
    }
    columns {
      name = "product_model"
      type = "string"
    }
    columns {
      name = "product_variant"
      type = "string"
    }
    columns {
      name = "condition"
      type = "string"
    }
    columns {
      name = "storage_gb"
      type = "int"
    }
    columns {
      name = "color"
      type = "string"
    }
    columns {
      name = "battery_health_pct"
      type = "int"
    }
    columns {
      name = "cycle_count"
      type = "int"
    }
    columns {
      name = "warranty_notes"
      type = "string"
    }
    columns {
      name = "includes_accessories"
      type = "string"
    }
    columns {
      name = "deal_score"
      type = "int"
    }
    columns {
      name = "is_great_deal"
      type = "boolean"
    }
    columns {
      name = "estimated_market_value"
      type = "double"
    }
    columns {
      name = "price_vs_market_pct"
      type = "double"
    }
    columns {
      name = "is_relevant_listing"
      type = "boolean"
    }
    columns {
      name = "notes"
      type = "string"
    }
    columns {
      name = "confidence"
      type = "string"
    }
    columns {
      name = "reason"
      type = "string"
    }
  }

  partition_keys {
    name = "category_key"
    type = "string"
  }
  partition_keys {
    name = "classified_date"
    type = "string"
  }
}
