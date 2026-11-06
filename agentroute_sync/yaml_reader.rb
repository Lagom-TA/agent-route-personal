require 'psych'
require 'json'

# Read YAML data through its syntax tree. In particular, ::1 must remain a string,
# not the Ruby Symbol produced by Psych's YAML 1.1 scalar loader.
class DataReader
  def initialize
    @anchors = {}
    @active = {}
    @aliases = 0
  end

  def value(node, depth = 0)
    raise 'YAML nesting too deep' if depth > 100
    if node.is_a?(Psych::Nodes::Alias)
      @aliases += 1
      raise 'YAML alias limit' if @aliases > 10000
      return value(@anchors.fetch(node.anchor), depth + 1)
    end
    @anchors[node.anchor] = node if node.respond_to?(:anchor) && node.anchor
    raise 'YAML alias cycle' if @active[node.object_id]
    @active[node.object_id] = true
    tag = node.respond_to?(:tag) ? node.tag : nil
    raise 'Custom YAML tag rejected' if tag && !tag.start_with?('tag:yaml.org,2002:')
    result = case node
    when Psych::Nodes::Document, Psych::Nodes::Stream
      node.children.empty? ? {} : value(node.children.first, depth + 1)
    when Psych::Nodes::Sequence
      node.children.map { |child| value(child, depth + 1) }
    when Psych::Nodes::Mapping
      merged = {}; specific = {}
      node.children.each_slice(2) do |key_node, value_node|
        key = key_node.value.to_s
        item = value(value_node, depth + 1)
        if key == '<<'
          (item.is_a?(Array) ? item : [item]).each do |m|
            raise 'Invalid merge' unless m.is_a?(Hash)
            merged = m.merge(merged)
          end
        else
          raise 'Duplicate YAML key' if specific.key?(key)
          specific[key] = item
        end
      end
      merged.merge(specific)
    when Psych::Nodes::Scalar
      text = node.value
      if node.quoted || tag == 'tag:yaml.org,2002:str'
        text
      elsif ['null', 'Null', 'NULL', '~', ''].include?(text)
        nil
      elsif ['true', 'True', 'TRUE'].include?(text)
        true
      elsif ['false', 'False', 'FALSE'].include?(text)
        false
      elsif text.match?(/\A[-+]?(0|[1-9][0-9]*)\z/)
        Integer(text, 10)
      elsif text.match?(/\A[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?\z/)
        Float(text)
      else
        text
      end
    else
      raise 'Unsupported YAML structure'
    end
    @active.delete(node.object_id)
    result
  end
end

puts JSON.generate(DataReader.new.value(Psych.parse_file(ARGV.fetch(0))) || {})
