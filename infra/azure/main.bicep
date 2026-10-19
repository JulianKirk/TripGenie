// TripGenie on Azure Container Apps. scripts/deploy/azure/deploy.sh renders
// `apps` from docker-compose.yml, so compose stays the one description of the
// services; this file only decides how each kind of service is hosted.
//
//   frontends + shared-ui   external HTTPS ingress, scale to zero when idle
//   backends + databases    internal TCP ingress on their compose port, so the
//                           compose URLs (http://student-1-database:8002) work
//                           unchanged; never reachable from the internet
//   databases               SQLite on an Azure Files share at the compose
//                           volume path
//
// AI-Mode, MCP, RAG and the Multi-Agent Server are not deployed: the cloud
// baseline keeps them disabled (shared/configuration/.env.cloud).

@description('Services rendered from docker-compose.yml by compose_to_azure.py.')
param apps array

@description('Registry login server that holds the tripgenie-* images.')
param registryServer string

@description('Resource ID of the user-assigned identity allowed to pull from the registry (scripts/deploy/azure/bootstrap.sh).')
param pullIdentityId string

param location string = resourceGroup().location

@description('Replicas kept warm for the public frontends. 0 is cheapest; set 1 for a demo to avoid cold starts.')
@minValue(0)
@maxValue(1)
param frontendMinReplicas int = 0

var dataApps = filter(apps, a => !empty(a.volumePath))

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'tripgenie-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'tripgenie${uniqueString(resourceGroup().id)}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
  }
}

resource files 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource shares 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = [
  for a in dataApps: {
    parent: files
    name: a.name
    properties: { shareQuota: 1 }
  }
]

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'tripgenie-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// The storage key goes straight from listKeys() into the environment and is
// never output or written anywhere else.
resource environmentStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = [
  for (a, i) in dataApps: {
    parent: environment
    name: a.name
    properties: {
      azureFile: {
        accountName: storage.name
        accountKey: storage.listKeys().keys[0].value
        shareName: shares[i].name
        accessMode: 'ReadWrite'
      }
    }
  }
]

resource containerApps 'Microsoft.App/containerApps@2024-03-01' = [
  for a in apps: {
    name: a.name
    location: location
    identity: {
      type: 'UserAssigned'
      userAssignedIdentities: { '${pullIdentityId}': {} }
    }
    dependsOn: [environmentStorage]
    properties: {
      managedEnvironmentId: environment.id
      configuration: {
        activeRevisionsMode: 'Single'
        registries: [{ server: registryServer, identity: pullIdentityId }]
        ingress: a.external
          ? { external: true, targetPort: a.port, transport: 'http', allowInsecure: false }
          : { external: false, targetPort: a.port, exposedPort: a.port, transport: 'tcp' }
      }
      template: {
        containers: [
          {
            name: a.name
            image: a.image
            resources: { cpu: json('0.25'), memory: '0.5Gi' }
            env: map(a.env, e => {
              name: e.name
              value: replace(e.value, '__DOMAIN__', environment.properties.defaultDomain)
            })
            volumeMounts: empty(a.volumePath) ? [] : [{ volumeName: 'data', mountPath: a.volumePath }]
          }
        ]
        // ponytail: one replica per app. SQLite on an SMB share has no file
        // locking (nobrl), so a database must never run two writers; move to
        // Azure SQL or Postgres before any service needs to scale out.
        scale: {
          minReplicas: a.external ? frontendMinReplicas : 1
          maxReplicas: 1
        }
        volumes: empty(a.volumePath)
          ? []
          : [
              {
                name: 'data'
                storageType: 'AzureFile'
                storageName: a.name
                // The images run as a non-root user; SMB has no POSIX owners.
                mountOptions: 'dir_mode=0777,file_mode=0777,nobrl,mfsymlinks,cache=none'
              }
            ]
      }
    }
  }
]

output urls array = [
  for (a, i) in apps: a.external ? 'https://${containerApps[i].properties.configuration.ingress.fqdn}' : ''
]
