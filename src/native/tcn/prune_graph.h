#pragma once
#include "graph_contract.h"
#include "generated_policy.h"
#include <algorithm>
#include <stdexcept>
#include <vector>
#include "tensorflow/lite/interpreter.h"
namespace gesture_i8_pruned {
inline void GraphRequire(bool yes,const char* why){if(!yes)throw std::runtime_error(why);}
inline std::vector<int> SelectedNodeIDs(){std::vector<int> ids;for(const auto& s:kSpecs)ids.push_back(s.node);return ids;}
inline void ValidateSelectedSpecs(){
  GraphRequire(kSelectedCount==5,"Nonempty approved hardware policy required");
  GraphRequire(size_t(kSelectedCount)==sizeof(kSpecs)/sizeof(kSpecs[0]),"Selected count differs");
  const auto ids=SelectedNodeIDs();GraphRequire(std::is_sorted(ids.begin(),ids.end()),"Selected original IDs not ordered");
  GraphRequire(std::adjacent_find(ids.begin(),ids.end())==ids.end(),"Duplicate selected original ID");
  for(const auto& s:kSpecs){GraphRequire(std::binary_search(std::begin(kKeptNodes),std::end(kKeptNodes),s.node),"Selected removed node");
    GraphRequire(s.node!=12&&s.node!=325&&s.allow_i8==1,"Sensitive node or unapproved selected contract");}
}
inline void ApplyPrunedGraph(tflite::Interpreter& interpreter){
  const std::vector<int> original(std::begin(kOriginalOutputs),std::end(kOriginalOutputs));
  const std::vector<int> kept(std::begin(kPrunedOutputs),std::end(kPrunedOutputs));
  GraphRequire(interpreter.outputs()==original,"Original output contract differs");
  const auto plan=interpreter.execution_plan();GraphRequire(plan.size()==332&&interpreter.nodes_size()==332,"Original node count differs");
  for(size_t i=0;i<plan.size();++i)GraphRequire(plan[i]==int(i),"Original node order differs");
  std::vector<int> producer(interpreter.tensors_size(),-1),pending=kept;
  std::vector<bool> live(332,false);
  for(int id:plan){const auto* row=interpreter.node_and_registration(id);
    GraphRequire(row&&row->first.inputs&&row->first.outputs&&!row->first.delegate,"Original graph metadata unavailable");
    for(int i=0;i<row->first.outputs->size;++i){int t=row->first.outputs->data[i];
      GraphRequire(t>=0&&size_t(t)<producer.size()&&producer[t]==-1,"Invalid/multiple producer");producer[t]=id;}}
  while(!pending.empty()){int t=pending.back();pending.pop_back();if(t<0)continue;
    GraphRequire(size_t(t)<producer.size(),"Invalid dependency tensor");int id=producer[t];if(id<0||live[id])continue;
    live[id]=true;const auto* row=interpreter.node_and_registration(id);
    for(int i=0;i<row->first.inputs->size;++i)pending.push_back(row->first.inputs->data[i]);}
  std::vector<int> actual;for(int id:plan)if(live[id])actual.push_back(id);
  const std::vector<int> expected(std::begin(kKeptNodes),std::end(kKeptNodes));
  GraphRequire(actual==expected&&actual.size()==286,"Backward reachability differs from 286-node contract");
  GraphRequire(interpreter.SetOutputs(kept)==kTfLiteOk,"SetOutputs failed");
  // TF2.11 public experimental mutable accessor; before first AllocateTensors.
  // The private SetExecutionPlan only bounds-checks then assigns this vector.
  interpreter.primary_subgraph().execution_plan()=actual;
  GraphRequire(interpreter.outputs()==kept&&interpreter.execution_plan()==expected,"Pruned graph not applied");
}
inline void ValidatePublicTensors(tflite::Interpreter& interpreter){
  GraphRequire(interpreter.inputs()==std::vector<int>{0},"Input tensor identity differs");
  const std::vector<int> ids(std::begin(kPrunedOutputs),std::end(kPrunedOutputs));
  GraphRequire(interpreter.outputs()==ids,"Four output tensor identities/order differ");
  const std::vector<std::vector<int>> shapes={{1,256,256,3},{1,195},{1,1},{1,64,64,39},{1,117}};
  const std::vector<int> all={0,337,342,298,339};
  for(size_t j=0;j<all.size();++j){const auto* t=interpreter.tensor(all[j]);
    GraphRequire(t&&t->type==kTfLiteFloat32&&t->dims&&t->data.raw,"Missing original FLOAT32 public tensor");
    GraphRequire(size_t(t->dims->size)==shapes[j].size(),"Public tensor rank differs");size_t count=1;
    for(size_t k=0;k<shapes[j].size();++k){GraphRequire(t->dims->data[k]==shapes[j][k],"Public tensor shape differs");count*=shapes[j][k];}
    GraphRequire(t->bytes==count*4,"Public tensor byte count differs");}
}
}
