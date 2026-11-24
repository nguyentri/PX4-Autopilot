// Validates sidecar output lines against schemas/bridge-protocol.schema.json
// with ajv (draft-07). Throws an AssertionError that names the failing line.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const Ajv = require('ajv');

const SCHEMA_PATH = path.resolve(__dirname, '..', 'schemas', 'bridge-protocol.schema.json');

function createValidator() {
  const ajv = new Ajv({ allErrors: true, strict: true, strictRequired: false, allowUnionTypes: true });
  ajv.addKeyword({ keyword: 'protocolVersion', schemaType: 'number' });
  const schema = JSON.parse(fs.readFileSync(SCHEMA_PATH, 'utf8'));
  const validateLine = ajv.compile(schema);
  const validateCommand = ajv.getSchema(`${schema.$id}#/definitions/command`);
  return {
    protocolVersion: schema.protocolVersion,
    line(message) {
      if (!validateLine(message)) {
        assert.fail(`sidecar line violates the protocol schema: ${JSON.stringify(message).slice(0, 400)}\n` +
          ajv.errorsText(validateLine.errors, { separator: '\n' }));
      }
    },
    command(message) {
      if (!validateCommand(message)) {
        assert.fail(`command violates the protocol schema: ${JSON.stringify(message)}\n` +
          ajv.errorsText(validateCommand.errors));
      }
    },
  };
}

module.exports = { createValidator, SCHEMA_PATH };
