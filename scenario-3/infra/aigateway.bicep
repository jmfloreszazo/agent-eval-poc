// ============================================================================
// Experiment 3 — Capa 2 — APIM AI Gateway in front of the Foundry/AOAI account.
//
// Additive to main.bicep. Re-uses:
//   * the existing Foundry / AOAI account  (param foundryAccountName)
//   * the existing Application Insights    (param appInsightsName)
//   * the existing Log Analytics workspace (param logAnalyticsWorkspaceName)
//
// Provisions:
//   * Azure AI Content Safety account      (required by <llm-content-safety>)
//   * APIM StandardV2 instance + system MI
//   * RBAC: APIM MI -> Cognitive Services User on AOAI + Content Safety
//   * Backends: aoai-backend, contentsafety-backend
//   * API "openai" imported from the Azure OpenAI OpenAPI spec
//   * Policy from scenario-3/infra/policies/aoai-policy.xml
//   * Product "corp-llm" + default subscription "corp-llm-default"
//   * Diagnostic settings -> existing Log Analytics + App Insights
//
// Outputs:
//   * gatewayUrl
//   * defaultSubscriptionPrimaryKey   (sensitive)
//   * apimName
// ============================================================================

@description('Base name (must match main.bicep). Default keeps the conventions.')
param baseName string = 'aieval3-${uniqueString(resourceGroup().id)}'

@description('Region. Match main.bicep.')
param location string = resourceGroup().location

@description('Existing Foundry / AOAI account name (output of main.bicep).')
param foundryAccountName string

@description('Existing Application Insights component name.')
param appInsightsName string

@description('Existing Log Analytics workspace name.')
param logAnalyticsWorkspaceName string

@description('Email shown as APIM publisher.')
param publisherEmail string = 'governance@corp.local'

@description('Name shown as APIM publisher.')
param publisherName string = 'Corp Governance'

@description('APIM SKU. StandardV2 is the minimum SKU with GenAI policies.')
@allowed([
  'StandardV2'
  'PremiumV2'
])
param apimSku string = 'StandardV2'

@description('AOAI deployment to route through APIM (must already exist on the Foundry account).')
param openAiDeploymentName string = 'gpt-4o-mini'

@description('AOAI data-plane API version to import.')
param openAiApiVersion string = '2024-10-21'

// ----------------------------------------------------------------------------
// Built-in role definitions
// ----------------------------------------------------------------------------
var roleCognitiveServicesUser = '/subscriptions/${subscription().subscriptionId}/providers/Microsoft.Authorization/roleDefinitions/a97b65f3-24c7-4388-baec-2e87135dc908'

// ----------------------------------------------------------------------------
// Existing resources we plug into
// ----------------------------------------------------------------------------
resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: foundryAccountName
}

resource appi 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

// ----------------------------------------------------------------------------
// Azure AI Content Safety account (for <llm-content-safety>)
// ----------------------------------------------------------------------------
resource contentSafety 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: '${baseName}-cs'
  location: location
  kind: 'ContentSafety'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: '${baseName}-cs'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

// ----------------------------------------------------------------------------
// APIM instance
// ----------------------------------------------------------------------------
resource apim 'Microsoft.ApiManagement/service@2024-06-01-preview' = {
  name: '${baseName}-apim'
  location: location
  sku: {
    name: apimSku
    capacity: 1
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    virtualNetworkType: 'None'
    publicNetworkAccess: 'Enabled'
  }
}

// APIM MI -> Cognitive Services User on the Foundry account
resource apimToFoundryRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(apim.id, foundry.id, 'cognitive-services-user')
  properties: {
    roleDefinitionId: roleCognitiveServicesUser
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// APIM MI -> Cognitive Services User on the Content Safety account
resource apimToContentSafetyRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: contentSafety
  name: guid(apim.id, contentSafety.id, 'cognitive-services-user')
  properties: {
    roleDefinitionId: roleCognitiveServicesUser
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ----------------------------------------------------------------------------
// Backends
// ----------------------------------------------------------------------------
resource aoaiBackend 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = {
  parent: apim
  name: 'aoai-backend'
  properties: {
    protocol: 'http'
    url: '${foundry.properties.endpoint}openai'
    description: 'Foundry/AOAI account (data-plane)'
  }
}

resource contentSafetyBackend 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = {
  parent: apim
  name: 'contentsafety-backend'
  properties: {
    protocol: 'http'
    url: contentSafety.properties.endpoint
    description: 'Azure AI Content Safety'
  }
}

// ----------------------------------------------------------------------------
// Logger -> Application Insights (so APIM request logs land in the same workspace)
// ----------------------------------------------------------------------------
resource appiLogger 'Microsoft.ApiManagement/service/loggers@2024-06-01-preview' = {
  parent: apim
  name: 'appi-logger'
  properties: {
    loggerType: 'applicationInsights'
    resourceId: appi.id
    credentials: {
      instrumentationKey: appi.properties.InstrumentationKey
    }
  }
}

// ----------------------------------------------------------------------------
// API: OpenAI inference (imported from the well-known OpenAPI URL)
// We use a relative apiUrlSuffix of "openai" so callers hit
//   https://<gateway>/openai/deployments/<name>/chat/completions?api-version=...
// exactly like the native AOAI endpoint.
// ----------------------------------------------------------------------------
resource openAiApi 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = {
  parent: apim
  name: 'openai'
  properties: {
    displayName: 'Azure OpenAI Inference'
    path: 'openai'
    protocols: [
      'https'
    ]
    serviceUrl: '${foundry.properties.endpoint}openai'
    subscriptionRequired: true
    format: 'openapi-link'
    value: 'https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/specification/cognitiveservices/data-plane/AzureOpenAI/inference/stable/${openAiApiVersion}/inference.json'
    apiType: 'http'
  }
}

resource openAiApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-06-01-preview' = {
  parent: openAiApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('policies/aoai-policy.xml')
  }
}

// Diagnostic settings: enable APIM -> App Insights request logging for the API
resource openAiApiDiagnostic 'Microsoft.ApiManagement/service/apis/diagnostics@2024-06-01-preview' = {
  parent: openAiApi
  name: 'applicationinsights'
  properties: {
    alwaysLog: 'allErrors'
    loggerId: appiLogger.id
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
    frontend: {
      request: {
        headers: [ 'X-Corp-Team', 'X-Corp-Actor', 'X-Corp-Agent', 'X-Corp-Corr-Id' ]
      }
      response: {
        headers: [ 'x-tokens-consumed', 'x-tokens-remaining', 'X-Corp-Corr-Id' ]
      }
    }
    backend: {
      request: {
        headers: [ 'X-Corp-Team', 'X-Corp-Actor', 'X-Corp-Agent', 'X-Corp-Corr-Id' ]
      }
      response: {
        headers: [ 'x-tokens-consumed', 'x-tokens-remaining' ]
      }
    }
  }
}

// ----------------------------------------------------------------------------
// Product + subscription (the api-key callers pass)
// ----------------------------------------------------------------------------
resource corpProduct 'Microsoft.ApiManagement/service/products@2024-06-01-preview' = {
  parent: apim
  name: 'corp-llm'
  properties: {
    displayName: 'Corp LLM'
    description: 'Governance-controlled access to corporate LLM backends.'
    subscriptionRequired: true
    approvalRequired: false
    state: 'published'
  }
}

resource corpProductApiLink 'Microsoft.ApiManagement/service/products/apiLinks@2024-06-01-preview' = {
  parent: corpProduct
  name: 'openai-link'
  properties: {
    apiId: openAiApi.id
  }
}

resource corpDefaultSubscription 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' = {
  parent: apim
  name: 'corp-llm-default'
  properties: {
    displayName: 'corp-llm default'
    scope: corpProduct.id
    state: 'active'
    allowTracing: false
  }
}

// ----------------------------------------------------------------------------
// Diagnostic settings for the APIM resource itself -> Log Analytics
// ----------------------------------------------------------------------------
resource apimToLawDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: apim
  name: 'apim-to-law'
  properties: {
    workspaceId: law.id
    logs: [
      {
        category: 'GatewayLogs'
        enabled: true
      }
      {
        category: 'WebSocketConnectionLogs'
        enabled: false
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// ----------------------------------------------------------------------------
// Outputs
// ----------------------------------------------------------------------------
output apimName string = apim.name
output gatewayUrl string = apim.properties.gatewayUrl
output openAiDeploymentName string = openAiDeploymentName
output openAiApiVersion string = openAiApiVersion
output contentSafetyEndpoint string = contentSafety.properties.endpoint
@secure()
output defaultSubscriptionPrimaryKey string = corpDefaultSubscription.listSecrets().primaryKey
