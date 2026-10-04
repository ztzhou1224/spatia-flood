import os, json, boto3, duckdb
s3=boto3.client('s3',endpoint_url=os.environ['CLOUDFLARE_R2_ENDPOINT'],aws_access_key_id=os.environ['CLOUDFLARE_R2_ACCESS_KEY_ID'],aws_secret_access_key=os.environ['CLOUDFLARE_R2_SECRET_ACCESS_KEY'],region_name='auto')
B=os.environ['CLOUDFLARE_R2_BUCKET']
M=json.loads(s3.get_object(Bucket=B,Key='contract/v2/manifest.json')['Body'].read())
def path(i): return f"s3://{B}/"+[L['storage_path'] for L in M['layers'] if L['id']==i][0]
def con():
    c=duckdb.connect(); c.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs; INSTALL h3 FROM community; LOAD h3; SET memory_limit='8GB'")
    ep=os.environ['CLOUDFLARE_R2_ENDPOINT'].replace('https://','')
    c.execute(f"CREATE SECRET (TYPE S3, KEY_ID '{os.environ['CLOUDFLARE_R2_ACCESS_KEY_ID']}', SECRET '{os.environ['CLOUDFLARE_R2_SECRET_ACCESS_KEY']}', ENDPOINT '{ep}', URL_STYLE 'path', REGION 'auto')")
    return c
