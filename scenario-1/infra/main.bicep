// Minimal Azure OpenAI resource for the evals PoC LLM-as-judge.
// Deploys:
//   - Azure OpenAI (kind=OpenAI, NOT Foundry) -> accepts API key without hassle
//   - gpt-4o-mini deployment (cheap, plenty for GEval)
// Output: endpoint + deployment name (fetch the key with `az`).

@description('Azure OpenAI account name. Must be globally unique.')
param accountName string = 'oai-${uniqueString(resourceGroup().id)}'

@description('Region. eastus2 / swedencentral usually have gpt-4o-mini available.')
param location string = 'eastus2'

@description('Model deployment name.')
param deploymentName string = 'gpt-4o-mini'

@description('gpt-4o-mini model version.')
param modelVersion string = '2024-07-18'

@description('Capacity (TPM in thousands). 10 = 10K tokens/min, more than enough for evals.')
param deploymentCapacity int = 10

resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: accountName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    // Allow both API key and Entra ID; this PoC uses the key for simplicity.
    disableLocalAuth: false
  }
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
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

output endpoint string = openAi.properties.endpoint
output accountName string = openAi.name
output deploymentName string = deployment.name
output resourceId string = openAi.id
