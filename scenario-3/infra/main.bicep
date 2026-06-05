// ============================================================================
// Experiment 3 — Dedicated Azure stack for the @corp governance gateway.
//
// Provisions an isolated set of resources so exp-3 can run independently
// of exp-2 (different RG, different App Insights, different Foundry
// project). Same shape as exp-2 because the Foundry evaluators we reuse
// (run_quality.py / run_safety.py) need the same surface.
//
// Resources:
//   * Log Analytics Workspace        (sink for App Insights)
//   * Application Insights           (where @corp emits spans)
//   * Azure AI Foundry account       (Cognitive Services kind=AIServices)
//   * Foundry Project                (where Foundry evaluators publish)
//   * gpt-4o-mini deployment         (LLM-as-judge for quality evals)
//   * RBAC (Cognitive Services User + Azure AI User) on the developer
//   * RBAC (Azure AI User) on the project's own MI (continuous eval)
//
// Outputs:
//   * foundryEndpoint, projectEndpoint, projectName, deploymentName
//   * appInsightsConnectionString    (consumed by scenario-3/src/telemetry.py)
//   * logAnalyticsWorkspaceId        (KQL queries under observability/kql)
// ============================================================================

@description('Base name. Used as a prefix for all resources.')
param baseName string = 'aieval3-${uniqueString(resourceGroup().id)}'

@description('Region. eastus2 / swedencentral usually have gpt-4o-mini and Foundry projects.')
param location string = 'eastus2'

@description('Name of the gpt-4o-mini deployment.')
param deploymentName string = 'gpt-4o-mini'

@description('gpt-4o-mini model version.')
param modelVersion string = '2024-07-18'

@description('Capacity (TPM in thousands). 10 = 10K tokens/min.')
param deploymentCapacity int = 10

@description('Object id of the developer (or SP) that should get data-plane access.')
param principalObjectId string = ''

@description('"User" or "ServicePrincipal" — used by role assignment.')
param principalType string = 'User'

// ----------------------------------------------------------------------------
// Built-in role definitions
// ----------------------------------------------------------------------------
var roleCognitiveServicesUser = '/subscriptions/${subscription().subscriptionId}/providers/Microsoft.Authorization/roleDefinitions/a97b65f3-24c7-4388-baec-2e87135dc908'
var roleAzureAIUser           = '/subscriptions/${subscription().subscriptionId}/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d'

// ----------------------------------------------------------------------------
// Observability
// ----------------------------------------------------------------------------
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${baseName}-law'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: '${baseName}-appi'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// ----------------------------------------------------------------------------
// Foundry account + project + appinsights connection
// ----------------------------------------------------------------------------
resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: '${baseName}-aifoundry'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: '${baseName}-aifoundry'
    publicNetworkAccess: 'Enabled'
    allowProjectManagement: true
    disableLocalAuth: false
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: foundry
  name: '${baseName}-project'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

resource projectAppInsights 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: project
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: appi.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: appi.properties.ConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appi.id
    }
  }
}

resource gpt4oMini 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: foundry
  name: deploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: deploymentCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o-mini'
      version: modelVersion
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

// ----------------------------------------------------------------------------
// RBAC
// ----------------------------------------------------------------------------
resource rbacCognitive 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalObjectId)) {
  scope: foundry
  name: guid(foundry.id, principalObjectId, roleCognitiveServicesUser)
  properties: {
    roleDefinitionId: roleCognitiveServicesUser
    principalId: principalObjectId
    principalType: principalType
  }
}

resource rbacAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalObjectId)) {
  scope: foundry
  name: guid(foundry.id, principalObjectId, roleAzureAIUser)
  properties: {
    roleDefinitionId: roleAzureAIUser
    principalId: principalObjectId
    principalType: principalType
  }
}

resource rbacProjectMiAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: project
  name: guid(project.id, 'project-mi', roleAzureAIUser)
  properties: {
    roleDefinitionId: roleAzureAIUser
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ----------------------------------------------------------------------------
// Outputs
// ----------------------------------------------------------------------------
output foundryAccountName string = foundry.name
output foundryEndpoint string = foundry.properties.endpoint
output projectName string = project.name
output projectEndpoint string = 'https://${foundry.name}.services.ai.azure.com/api/projects/${project.name}'
output deploymentName string = gpt4oMini.name
output appInsightsConnectionString string = appi.properties.ConnectionString
output appInsightsResourceId string = appi.id
output projectPrincipalId string = project.identity.principalId
output logAnalyticsWorkspaceId string = law.properties.customerId
output logAnalyticsResourceId string = law.id
output resourceGroupName string = resourceGroup().name
output subscriptionId string = subscription().subscriptionId
