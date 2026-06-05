// ============================================================================
// Experiment 2 — Azure AI Foundry stack for evaluations & governance demos.
//
// Resources:
//   * Log Analytics Workspace        (telemetry sink for App Insights + KQL)
//   * Application Insights           (workspace-based, captures agent traces)
//   * Azure AI Foundry account       (Cognitive Services kind=AIServices,
//                                     allowProjectManagement=true)
//   * Foundry Project                (where Foundry evaluators land)
//   * gpt-4o-mini deployment         (model under test + LLM-as-judge)
//   * RBAC                           ("Cognitive Services User" + "Azure AI
//                                     User" on the deployer object id)
//
// Outputs:
//   * foundryEndpoint, projectEndpoint, projectName, deploymentName
//   * appInsightsConnectionString    (used by the agent OTLP exporter)
//   * logAnalyticsWorkspaceId        (governance KQL queries run here)
// ============================================================================

@description('Base name. Used as a prefix for all resources to keep them grouped.')
param baseName string = 'aieval2-${uniqueString(resourceGroup().id)}'

@description('Region. eastus2 / swedencentral usually have gpt-4o-mini and Foundry projects.')
param location string = 'eastus2'

@description('Name of the gpt-4o-mini deployment.')
param deploymentName string = 'gpt-4o-mini'

@description('gpt-4o-mini model version.')
param modelVersion string = '2024-07-18'

@description('Capacity (TPM in thousands). 10 = 10K tokens/min.')
param deploymentCapacity int = 10

@description('Object id of the developer (or service principal) that should get data-plane access. Default: current user, fill in via deploy.ps1.')
param principalObjectId string = ''

@description('"User" or "ServicePrincipal" — used by role assignment.')
param principalType string = 'User'

// ----------------------------------------------------------------------------
// Built-in role definitions (used for assignments below)
// ----------------------------------------------------------------------------
var roleCognitiveServicesUser = '/subscriptions/${subscription().subscriptionId}/providers/Microsoft.Authorization/roleDefinitions/a97b65f3-24c7-4388-baec-2e87135dc908'
var roleAzureAIUser           = '/subscriptions/${subscription().subscriptionId}/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d'

// ----------------------------------------------------------------------------
// Observability: Log Analytics + App Insights (workspace-based)
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
// Foundry account (the new "AI Services with project management") + project
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
    // This flag turns the account into a Foundry account (hosts projects).
    allowProjectManagement: true
    // Allow both API key and Entra ID; the demo uses Entra ID for evaluators.
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

// Link the Application Insights resource to the Foundry project so that
// agent traces appear under Project → Tracing / Monitoring in the portal.
// Without this connection the OTel data still lands in App Insights, but
// the Foundry UI does not surface it. Some regions auto-create a
// connection named `appInsights-connection-<n>` the first time the
// project is provisioned; we deliberately use a deterministic name so
// the Bicep is idempotent. If a deployment fails with "Multiple
// connection with same category (AppInsights)", delete the auto-created
// one first: az rest --method delete --uri <connection-id>?api-version=2025-04-01-preview
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
// RBAC — give the developer data-plane access without managing keys.
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

// Continuous evaluation requires the project's *own* system-assigned managed
// identity to hold the Foundry User role (a.k.a. Azure AI User, role id
// 53ca6127-...) on the project scope. Without this, EvaluationRule creation
// succeeds but the rule never produces results.
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
